"""Derive SGGS tags by embedding similarity to curated concept prototypes.

Replaces LLM string-voting, which was a frequency-biased sieve: it selected for
*agreeability*, not correctness. Generic labels have one surface form and every
model emits them ("Divine Grace" was proposed on 96% of the corpus); specific
concepts fragment across dozens of forms ("ego" appeared as 40 distinct strings),
so two models rarely produced the same string for the same shabad. Median
survival was 41% for the twenty most-proposed tags and 2% for the forty least.
Result: only 21% of the 463 shabads that literally say ਹਉਮੈ were tagged Haumai,
and four of the five thieves (kaam, krodh, moh, ahankar) had no tag at all.

Here, each concept is a prototype vector, and every one of the ~57k verses is
scored against every prototype. Nothing depends on models agreeing on a string.

Prototype construction, per concept:
  - embed the concept's English description (verses are embedded on their English
    translation, so the description must read the way BaniDB renders the idea)
  - where the concept has Gurmukhi anchors, add the centroid of the verses that
    literally contain one — those are near-certain positives
  - blend 40% description / 60% lexical centroid; description-only concepts
    (Vismad, Birha, Chardi Kala, Nimrata) rest on the description alone and are
    marked lower-confidence

Thresholds are calibrated per concept, not fixed: a threshold is chosen to
capture TARGET_ANCHOR_RECALL of that concept's lexical anchors. A concept whose
language is diffuse therefore gets a looser threshold than one whose language is
sharp, which a single global cosine cutoff could never do.

Anchors are seeds, not rules. A shabad that teaches ego without ever saying
ਹਉਮੈ still gets tagged, because the assignment is by meaning.

Usage:
    python bootstrap/build_concept_tags.py --dry-run    # report only, writes nothing
    python bootstrap/build_concept_tags.py              # writes tags + vocabulary

Outputs (non-dry-run):
    data/concept_tags.json   {shabad_id: [{concept, strength, line_index, line_gurmukhi}]}
    data/tag_vocabulary.json {theme_tags: {concept: {count, description, ...}}}
    data/concept_tag_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from database.vector_store import ShabadVectorStore

VOCAB_PATH = Path(config.DATA_DIR) / "draft_vocabulary.json"
TAGS_OUT = Path(config.DATA_DIR) / "concept_tags.json"
VOCAB_OUT = Path(config.DATA_DIR) / "tag_vocabulary.json"
REPORT_OUT = Path(config.DATA_DIR) / "concept_tag_report.md"

# Capture this fraction of a concept's lexical anchors. The rest of the
# distribution is where generalization lives — verses that teach the concept
# without naming it.
TARGET_ANCHOR_RECALL = 0.75
# A concept on more than this share of the corpus is structural. It stays a tag
# (searchable, filterable) but api/graph_api.py bars it from titling a cluster.
MAX_PREVALENCE = 0.35
# How far past the literal word a concept may reach. Calibrating on anchor recall
# alone gives a diffuse concept a loose threshold and lets it swallow the corpus
# (Vichar reached 1,814 shabads from 294 that name it). A concept may INFER at most
# this multiple of the shabads that say its word outright — the evidence the corpus
# supplies bounds the inference it licenses.
GENERALIZATION_BUDGET = 2.0
# A literal mention beats an inferred one when a shabad's tags are trimmed. Exceeds
# any normalized margin (which lives in [0,1]), so lexical assignments sort first.
ANCHOR_MARGIN_BONUS = 1.0
# Below this many anchor verses we cannot calibrate; fall back to a percentile.
MIN_ANCHOR_LINES = 20
DESC_WEIGHT, SEED_WEIGHT = 0.4, 0.6
# Keep tag sets tight: a shabad's strongest concepts, not everything it brushes.
MAX_TAGS_PER_SHABAD = 6


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def load_vocabulary(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    concepts = doc.get("concepts", doc)
    return {k: v for k, v in concepts.items() if v.get("include", True)}


def lexical_line_positives(concepts: dict) -> dict[str, set[str]]:
    """Verse ids ("{shabad}:{index}") whose Gurmukhi carries a concept's anchor.

    Matching is on whitespace tokens with prefix rules, never raw substring:
    ਮੋਹ as a substring also matches ਮੋਹਨ (a name of God), and ਕਾਮ matches
    ਕਾਮਣਿ (the soul-bride). Those false positives would poison the prototypes.
    """
    db = sqlite3.connect(config.CACHE_DB_PATH)
    hits: dict[str, set[str]] = {c: set() for c in concepts}
    for shabad_id, response in db.execute("SELECT shabad_id, response FROM shabad_cache"):
        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            continue
        for idx, verse in enumerate(data.get("verses", [])):
            gur = nfc((verse.get("verse") or {}).get("unicode", ""))
            if not gur:
                continue
            tokens = [t for t in re.sub(r"[॥।0-9੦-੯]", " ", gur).split() if t]
            for name, c in concepts.items():
                acc, rej = c.get("anchors_accept", []), c.get("anchors_reject", [])
                if not acc:
                    continue
                for t in tokens:
                    if any(t.startswith(a) for a in acc) and not any(t.startswith(r) for r in rej):
                        hits[name].add(f"{shabad_id}:{idx}")
                        break
    db.close()
    return hits


def load_line_vectors(store: ShabadVectorStore):
    """All verse vectors, L2-normalized, paged (ChromaDB caps SQL variables)."""
    total = store.get_count()
    vecs, metas, ids = [], [], []
    for offset in range(0, total, 2000):
        page = store.collection.get(include=["embeddings", "metadatas"], limit=2000, offset=offset)
        vecs.append(np.array(page["embeddings"], dtype=np.float32))
        metas.extend(page["metadatas"])
        ids.extend(page["ids"])
    E = np.vstack(vecs)
    E /= np.linalg.norm(E, axis=1, keepdims=True) + 1e-9
    return E, metas, ids


def build_prototype(desc_vec, seed_rows, E):
    if len(seed_rows) >= MIN_ANCHOR_LINES:
        centroid = E[seed_rows].mean(axis=0)
        centroid /= np.linalg.norm(centroid) + 1e-9
        proto = DESC_WEIGHT * desc_vec + SEED_WEIGHT * centroid
    else:
        proto = desc_vec
    return proto / (np.linalg.norm(proto) + 1e-9)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vocab", type=Path, default=VOCAB_PATH)
    ap.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
    ap.add_argument("--sample", type=int, default=2, help="Sample verses per concept in the report.")
    args = ap.parse_args()

    concepts = load_vocabulary(args.vocab)
    print(f"Vocabulary: {len(concepts)} concepts from {args.vocab.name}")

    print("Scanning corpus for lexical anchors...")
    anchors = lexical_line_positives(concepts)

    print("Loading verse vectors...")
    store = ShabadVectorStore(collection_name=config.SGGS_LINES_COLLECTION_NAME)
    E, metas, ids = load_line_vectors(store)
    row_of = {i: n for n, i in enumerate(ids)}
    line_sid = np.array([m["shabad_id"] for m in metas])
    print(f"  {E.shape[0]} verses x {E.shape[1]} dims")

    fn = store.embedding_fn
    n_shabads = len(set(line_sid))

    assignments: dict[str, list[dict]] = {}
    report_rows = []

    for name, c in concepts.items():
        desc_vec = np.array(fn([c["description"]])[0], dtype=np.float32)
        desc_vec /= np.linalg.norm(desc_vec) + 1e-9
        seed_rows = [row_of[l] for l in anchors[name] if l in row_of]
        proto = build_prototype(desc_vec, seed_rows, E)

        sim = E @ proto

        # Calibrate: capture TARGET_ANCHOR_RECALL of this concept's anchor verses.
        if len(seed_rows) >= MIN_ANCHOR_LINES:
            anchor_scores = np.sort(sim[seed_rows])[::-1]
            thr = float(anchor_scores[int(len(anchor_scores) * TARGET_ANCHOR_RECALL) - 1])
            calib = "lexical"
        else:
            thr = float(np.quantile(sim, 0.995))  # description-only: top 0.5% of verses
            calib = "description-only"

        def best_line_over(rows) -> dict[str, tuple[float, int, str]]:
            out: dict[str, tuple[float, int, str]] = {}
            for row in rows:
                s = line_sid[row]
                if sim[row] > out.get(s, (-1,))[0]:
                    out[s] = (float(sim[row]), metas[row]["line_index"], metas[row]["gurmukhi"])
            return out

        # A shabad that literally names the concept IS about the concept. The word
        # is ground truth, not a candidate — the prototype may only ADD shabads
        # that never say it. (Anchors serve double duty: here they are production
        # truth; in the calibration above they are the held-out yardstick that
        # tells us whether the prototype generalizes at all.)
        anchor_best = best_line_over(seed_rows)
        thresholded = best_line_over(np.where(sim >= thr)[0])
        generalized = {s: v for s, v in thresholded.items() if s not in anchor_best}

        # Two ceilings on how far past the literal word a concept may reach: it may
        # never swallow the corpus, and its inferred additions are budgeted against
        # the evidence that the word itself supplies.
        ceiling = max(0, int(MAX_PREVALENCE * n_shabads) - len(anchor_best))
        if anchor_best:
            ceiling = min(ceiling, int(GENERALIZATION_BUDGET * len(anchor_best)))
        if len(generalized) > ceiling:
            generalized = dict(sorted(generalized.items(), key=lambda kv: -kv[1][0])[:ceiling])

        # Scores are NOT comparable across concepts — each has its own threshold and
        # its own score scale. Rank by margin above threshold, normalized, so that
        # trimming a shabad to MAX_TAGS_PER_SHABAD cannot truncate away a pointed
        # concept (Krodh) in favor of one whose raw cosine simply runs higher.
        # Without this, the frequency bias we set out to kill comes straight back.
        # Literal mentions outrank every inferred one.
        span = max(1e-6, 1.0 - thr)
        for pool, bonus in ((anchor_best, ANCHOR_MARGIN_BONUS), (generalized, 0.0)):
            for sid, (score, li, gur) in pool.items():
                assignments.setdefault(sid, []).append({
                    "concept": name,
                    "strength": round(score, 3),
                    "margin": round(bonus + (score - thr) / span, 4),
                    "lexical": bonus > 0,
                    "line_index": li,
                    "line_gurmukhi": gur,
                })
        best_by_shabad = {**anchor_best, **generalized}

        # Would the prototype have found the anchors on its own? Anchors are forced
        # into the output above, so this must be measured against the unforced
        # thresholded set or the number is a tautology. A low value means the
        # concept's description points somewhere other than its own word.
        gen_recall = len(set(anchor_best) & set(thresholded)) / max(1, len(anchor_best))
        report_rows.append({
            "concept": name, "group": c.get("group", ""), "calib": calib,
            "anchor_shabads": len(anchor_best), "generalized": len(generalized),
            "tagged": len(best_by_shabad), "gen_recall": gen_recall,
            "threshold": round(thr, 3),
            "samples": sorted(generalized.items(), key=lambda kv: -kv[1][0])[: args.sample],
        })

    # Keep each shabad's strongest concepts, ranked by normalized margin.
    for sid, lst in assignments.items():
        lst.sort(key=lambda a: -a["margin"])
        del lst[MAX_TAGS_PER_SHABAD:]

    counts: dict[str, int] = {}
    for lst in assignments.values():
        for a in lst:
            counts[a["concept"]] = counts.get(a["concept"], 0) + 1

    print(f"\n{'concept':<14} {'grp':<9} {'calib':<17} {'says it':>8} {'+infer':>7} "
          f"{'tagged':>7} {'gen-rec':>8}")
    print("-" * 82)
    for r in sorted(report_rows, key=lambda r: -counts.get(r["concept"], 0)):
        final = counts.get(r["concept"], 0)
        print(f"{r['concept']:<14} {r['group']:<9} {r['calib']:<17} {r['anchor_shabads']:>8} "
              f"{r['generalized']:>7} {final:>7} {r['gen_recall']:>7.0%}")

    tagged_shabads = len(assignments)
    avg = sum(len(v) for v in assignments.values()) / max(1, tagged_shabads)
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:1]
    print(f"\nshabads tagged: {tagged_shabads}/{n_shabads}   avg tags/shabad: {avg:.1f}")
    if top:
        print(f"top concept: {top[0][0]} @ {top[0][1]/n_shabads:.0%} coverage")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    TAGS_OUT.write_text(json.dumps(assignments, ensure_ascii=False, indent=2), encoding="utf-8")

    # Point the corpus file at the new taxonomy — build_graph.py and the app read
    # tags from sggs_all_shabads.json, not from concept_tags.json. Shabads the
    # tagger did not reach get an empty list; build_graph gives them
    # embedding-only neighbors.
    corpus_path = Path(config.SGGS_DATA_PATH)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    for rec in corpus:
        sid = str(rec.get("banidb_shabad_id"))
        rec["tags"] = [a["concept"] for a in assignments.get(sid, [])]
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"updated tags in {corpus_path.name}")
    theme_tags = {
        name: {
            "count": counts.get(name, 0),
            "description": c["description"],
            "group": c.get("group", ""),
            "confidence": c.get("confidence", ""),
            "gurbani_term": " ".join(c.get("anchors_accept", [])),
        }
        for name, c in concepts.items()
        if counts.get(name, 0) > 0
    }
    VOCAB_OUT.write_text(json.dumps({"theme_tags": theme_tags, "mood_tags": {}}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Concept tagging report", "", f"{tagged_shabads} shabads tagged, avg {avg:.1f} tags each.", ""]
    lines += ["| concept | group | calibration | says it | inferred | tagged | gen. recall |",
              "|---|---|---|---:|---:|---:|---:|"]
    for r in sorted(report_rows, key=lambda r: -counts.get(r["concept"], 0)):
        lines.append(f"| {r['concept']} | {r['group']} | {r['calib']} | {r['anchor_shabads']} | "
                     f"{r['generalized']} | {counts.get(r['concept'],0)} | {r['gen_recall']:.0%} |")
    REPORT_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {TAGS_OUT.name}, {VOCAB_OUT.name}, {REPORT_OUT.name}")


if __name__ == "__main__":
    main()
