"""Multi-LLM consensus tagging for SGGS shabads.

Replaces the single-LLM enrichment pipeline (enrich_sggs.py + tag_shabads.py)
with a four-LLM consensus pass. Each LLM tags every shabad independently;
final tags are the ones agreed by at least two LLMs. Full per-LLM reasoning
is preserved so the UI can later show "Tagged X because Y" tooltips.

LLM lineup:
  - qwen3:14b           (Ollama, local)         — strong general reasoner
  - deepseek-r1:14b     (Ollama, local)         — independent training family
  - gemma2:27b          (Ollama, local)         — Google family, larger context
  - claude-sonnet-4-5   (Anthropic API)         — most aligned with Sikh context
                                                  in our pilot tests; tiebreaker

Run order (each pass is resumable; stop and resume any time):

    python bootstrap/multi_llm_tag.py --llm qwen3:14b
    python bootstrap/multi_llm_tag.py --llm deepseek-r1:14b
    python bootstrap/multi_llm_tag.py --llm gemma2:27b
    python bootstrap/multi_llm_tag.py --llm claude-sonnet-4-5
    python bootstrap/multi_llm_tag.py --consensus

Each pass writes to data/tag_reasoning.json keyed by shabad_id → llm_name → result.
The final --consensus step merges results, applies the voting rule, and writes
the canonical tags back to data/sggs_all_shabads.json plus a new tag_vocabulary.json.

A single shabad costs roughly:
  - Ollama: free, ~5-15s per call depending on model size (M-series Mac)
  - Anthropic claude-sonnet-4-5: ~400 input + 300 output tokens
                                 → ~$0.0057 per shabad → ~$32 for 5,542 shabads

The consensus rule (--consensus pass):
  - A tag is canonical for a shabad if it appears in at least 2 of 4 LLM responses
    (case-insensitive comparison, simple morphological normalization for variants)
  - Singleton tags (only one LLM proposed) are dropped — pure noise reduction
  - Tied 2-2 splits keep both candidate tags; Claude's vote breaks ties only when
    the question is "which of two synonyms to keep" (handled in Phase C taxonomy
    build, not here)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

# ---- Paths ------------------------------------------------------------------

SGGS_PATH = Path(config.SGGS_DATA_PATH)
# Per-LLM reasoning files prevent the multi-process write race we hit when
# three runs shared a single tag_reasoning.json: each process held its own
# in-memory snapshot and overwrote the others' saves. The merged file is
# rebuilt by --consensus from the per-LLM shards.
REASONING_DIR = Path(config.DATA_DIR) / "tag_reasoning"
REASONING_MERGED_PATH = Path(config.DATA_DIR) / "tag_reasoning.json"
NEW_VOCAB_PATH = Path(config.DATA_DIR) / "tag_vocabulary.json"

# ---- LLM identifiers --------------------------------------------------------

# gemma2:27b kept as a permitted name even though we're not running it in this
# pass — leaves the option open without forcing a code change later.
OLLAMA_LLMS = {"qwen3:14b", "deepseek-r1:14b", "llama3.1:8b", "gemma2:27b"}
ANTHROPIC_LLMS = {"claude-sonnet-4-5"}
ALL_LLMS = sorted(OLLAMA_LLMS | ANTHROPIC_LLMS)
# The four LLMs actually used in this consensus pass (Meta + Alibaba +
# DeepSeek-AI + Anthropic — four independent training families).
CONSENSUS_LLMS = ["qwen3:14b", "deepseek-r1:14b", "llama3.1:8b", "claude-sonnet-4-5"]

# ---- Prompt -----------------------------------------------------------------

PROMPT_TEMPLATE = """You are tagging a Sikh Gurbani shabad from Sri Guru Granth Sahib Ji.

Translation:
{translation}

Rahao (core verse):
{rahao}

Return a JSON object with exactly these keys:

  "primary_theme":  one short phrase (2-4 words) capturing the dominant spiritual theme.
                    Use canonical Gurbani terms when applicable (e.g. "Hukam", "Naam Simran",
                    "Vichola", "Bhakti", "Vairag"). Avoid vague phrases like "Spiritual life".
  "mood":           one short phrase capturing emotional register (e.g. "Devotional longing",
                    "Joyful praise", "Contemplative peace", "Fearful surrender").
  "brief_meaning":  one sentence in plain English summarizing what the shabad teaches.
  "tags":           a JSON array of 3-6 short canonical tags. Use established Sikhi vocabulary
                    where possible. Common tags include: "Hukam", "Naam Simran", "Vairag",
                    "Bhakti", "Surrender", "Divine Grace", "Maya", "Birha", "Sangat",
                    "Guru's Wisdom", "Chardi Kala", "Anand", "Vichola", "Awe", "Humility".
                    Each tag should be 1-3 words.
  "reasoning":      one sentence explaining WHY you chose these tags. Reference specific
                    imagery, phrases, or arcs in the translation.

Return ONLY the JSON object — no preamble, no markdown fences, no commentary."""

# ---- LLM dispatchers --------------------------------------------------------

def call_ollama(model: str, prompt: str, max_tokens: int = 800) -> dict:
    """Run a single Ollama generation. Raises on hard errors; caller decides retry."""
    import ollama as _ollama

    client = _ollama.Client(host=config.OLLAMA_BASE_URL)
    response = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={"num_predict": max_tokens, "temperature": 0.2},
        think=False,
    )
    text = response.message.content.strip()
    return json.loads(text)


def call_anthropic(model: str, prompt: str, max_tokens: int = 800) -> dict:
    """Run a single Anthropic message generation. Retries on 429 with exponential backoff.

    Free-tier accounts hit 50 RPM and 8K output tokens/min limits quickly. We
    back off long enough to clear a fresh minute window rather than hammering.
    """
    import anthropic

    client = anthropic.Anthropic()
    last_err = None
    for attempt in range(6):
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip()
            # Strip any accidental markdown fences just in case.
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
            return json.loads(text)
        except anthropic.RateLimitError as err:
            last_err = err
            # 5s, 15s, 35s, 75s, 155s, 315s — covers up to ~10 minutes of backoff.
            wait = 5 * (2**attempt) + 5
            time.sleep(wait)
        except anthropic.APIStatusError as err:
            # 5xx are worth retrying; 4xx other than 429 are fatal.
            if 500 <= err.status_code < 600:
                last_err = err
                time.sleep(5 * (attempt + 1))
            else:
                raise
    raise RuntimeError(f"anthropic exhausted retries: {last_err}")


def tag_one(llm: str, shabad: dict) -> dict:
    """Tag a single shabad with a single LLM. Returns the parsed result + raw timing."""
    prompt = PROMPT_TEMPLATE.format(
        translation=(shabad.get("english_translation") or "")[:1200],
        rahao=(shabad.get("rahao_english") or "(no rahao)")[:400],
    )
    started = time.time()
    if llm in OLLAMA_LLMS:
        result = call_ollama(llm, prompt)
    elif llm in ANTHROPIC_LLMS:
        result = call_anthropic(llm, prompt)
    else:
        raise ValueError(f"Unknown LLM: {llm}")
    return {
        "primary_theme": result.get("primary_theme", ""),
        "mood": result.get("mood", ""),
        "brief_meaning": result.get("brief_meaning", ""),
        "tags": list(result.get("tags", [])) if isinstance(result.get("tags"), list) else [],
        "reasoning": result.get("reasoning", ""),
        "elapsed_s": round(time.time() - started, 2),
    }


# ---- Reasoning store --------------------------------------------------------

def _llm_to_filename(llm: str) -> str:
    """Convert LLM name to a safe filename (e.g. 'qwen3:14b' → 'qwen3_14b.json')."""
    return llm.replace(":", "_").replace("/", "_") + ".json"


def llm_reasoning_path(llm: str) -> Path:
    """Per-LLM reasoning file path (one file per LLM, no write contention)."""
    return REASONING_DIR / _llm_to_filename(llm)


def load_llm_reasoning(llm: str) -> dict:
    """Load this LLM's reasoning shard. Falls back to merged file for back-compat
    on the first run after the per-LLM split (so we don't lose existing data).
    """
    REASONING_DIR.mkdir(parents=True, exist_ok=True)
    p = llm_reasoning_path(llm)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    # Fallback: pull this LLM's slice out of the legacy merged file.
    if REASONING_MERGED_PATH.exists():
        legacy = json.loads(REASONING_MERGED_PATH.read_text(encoding="utf-8"))
        return {sid: r[llm] for sid, r in legacy.items() if isinstance(r, dict) and llm in r}
    return {}


def save_llm_reasoning(llm: str, shabad_to_result: dict) -> None:
    """Save this LLM's reasoning shard. {shabad_id: result}."""
    REASONING_DIR.mkdir(parents=True, exist_ok=True)
    llm_reasoning_path(llm).write_text(
        json.dumps(shabad_to_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_merged_reasoning() -> dict:
    """Merge all per-LLM shards into the consolidated {shabad_id: {llm: result}} shape.

    Used by the --consensus pass and by anything that wants the unified view.
    Always re-reads from disk so it sees the latest writes from any in-flight
    process.
    """
    merged: dict = {}
    if REASONING_DIR.exists():
        for p in REASONING_DIR.glob("*.json"):
            llm_name_from_file = p.stem.replace("_", ":", 1) if "_" in p.stem else p.stem
            # Recover original LLM names: 'qwen3_14b' → 'qwen3:14b',
            # 'claude-sonnet-4-5' → 'claude-sonnet-4-5'
            for known in ALL_LLMS:
                if _llm_to_filename(known) == p.name:
                    llm_name_from_file = known
                    break
            shard = json.loads(p.read_text(encoding="utf-8"))
            for sid, result in shard.items():
                merged.setdefault(sid, {})[llm_name_from_file] = result
    elif REASONING_MERGED_PATH.exists():
        # Legacy single-file fallback.
        merged = json.loads(REASONING_MERGED_PATH.read_text(encoding="utf-8"))
    return merged


# ---- Per-LLM pass -----------------------------------------------------------

def run_pass(llm: str, max_concurrent: int, save_every: int, limit: int | None) -> None:
    if llm not in ALL_LLMS:
        raise SystemExit(f"Unknown LLM '{llm}'. Choose from: {', '.join(ALL_LLMS)}")

    print(f"Loading SGGS shabads from {SGGS_PATH}...")
    shabads = json.loads(SGGS_PATH.read_text(encoding="utf-8"))
    print(f"  {len(shabads)} shabads loaded.")

    shard = load_llm_reasoning(llm)

    # Load AK source map so we can prioritize Amrit Keertan shabads.
    # The flip-the-script methodology: tag the 2,078 AK shabads first across
    # all four LLMs so we can derive a tradition-grounded taxonomy from canon
    # before tagging the remaining 3,464 non-AK shabads. The non-AK pass will
    # then prompt with the AK-derived vocabulary as a constraint.
    sources_path = Path(config.DATA_DIR) / "sggs_sources.json"
    ak_set: set[str] = set()
    if sources_path.exists():
        sources_data = json.loads(sources_path.read_text(encoding="utf-8"))
        ak_set = {sid for sid, fields in sources_data.items() if fields.get("amrit_keertan")}

    pending = []
    skipped = 0
    for s in shabads:
        sid = str(s.get("banidb_shabad_id"))
        if not sid or not s.get("english_translation"):
            continue
        prev = shard.get(sid)
        # Skip only successful results. Treat error rows as "not done" so resume retries them.
        if isinstance(prev, dict) and "tags" in prev and not prev.get("error"):
            skipped += 1
            continue
        pending.append(s)

    # AK-first ordering: process Amrit Keertan shabads before non-AK ones.
    # ang_number breaks ties so we still walk SGGS in a sensible reading order
    # within each group.
    pending.sort(key=lambda s: (
        0 if str(s.get("banidb_shabad_id")) in ak_set else 1,
        s.get("ang_number", 0),
        int(s.get("banidb_shabad_id", 0) or 0),
    ))
    ak_pending = sum(1 for s in pending if str(s.get("banidb_shabad_id")) in ak_set)
    print(f"  AK shabads pending: {ak_pending} (will be processed first)")

    if limit is not None:
        pending = pending[:limit]

    print(f"  {skipped} already done with {llm}; {len(pending)} remaining.")
    if not pending:
        print("Nothing to do.")
        return

    # Concurrency:
    # - Ollama on a single local model: cap at 2 so the GPU isn't thrashed.
    #   Each in-flight call holds the model warm.
    # - Anthropic: paid Tier 1+ supports 1,000+ RPM, so we honor the requested
    #   concurrency directly. Free-tier (50 RPM) callers should pass --concurrency 2.
    if llm in OLLAMA_LLMS:
        concurrency = max(1, min(max_concurrent, 2))
    else:
        concurrency = max(1, max_concurrent)

    print(f"  Running with concurrency={concurrency}; saving every {save_every} shabads.")
    print()

    started = time.time()
    completed = 0
    failed = 0

    def submit(executor: ThreadPoolExecutor, item: dict):
        return executor.submit(tag_one, llm, item)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_shabad = {submit(executor, s): s for s in pending}
        for future in as_completed(future_to_shabad):
            shabad = future_to_shabad[future]
            sid = str(shabad["banidb_shabad_id"])
            try:
                result = future.result()
                shard[sid] = result
                completed += 1
            except Exception as err:
                failed += 1
                err_summary = str(err)[:200]
                shard[sid] = {"error": err_summary}
                print(f"  shabad {sid} failed: {err_summary}")

            if (completed + failed) % save_every == 0:
                save_llm_reasoning(llm, shard)
                rate = (completed + failed) / max(1, time.time() - started)
                eta_s = (len(pending) - completed - failed) / max(rate, 0.001)
                print(
                    f"  progress: {completed + failed}/{len(pending)} "
                    f"(ok={completed}, fail={failed}, "
                    f"rate={rate:.2f}/s, eta={eta_s/60:.1f} min)"
                )

    save_llm_reasoning(llm, shard)
    elapsed = time.time() - started
    print(f"\nDone with {llm}. ok={completed}, fail={failed}, elapsed={elapsed/60:.1f} min")


# ---- Consensus --------------------------------------------------------------

_TAG_NORM_RE = re.compile(r"[^a-z0-9]+")


def normalize_tag(tag: str) -> str:
    """Lowercase + strip non-alphanum so 'Naam Simran' == 'naam-simran' == 'NaamSimran'.
    This collapses obvious surface variants without doing fancy stemming.
    """
    return _TAG_NORM_RE.sub("", tag.lower()).strip()


def consensus_tags(per_llm_tags: dict[str, list[str]], min_votes: int = 2) -> tuple[list[str], dict]:
    """Apply the consensus rule.

    Returns:
        (canonical_tags, vote_detail)
        canonical_tags: ordered list of agreed tags (first-seen surface form per
                        normalized key, ordered by vote count desc)
        vote_detail: {normalized_tag: {votes, surface_forms, voters}}
    """
    bucket: dict[str, dict] = {}
    for llm, tags in per_llm_tags.items():
        seen_in_this_llm: set[str] = set()
        for tag in tags or []:
            if not isinstance(tag, str):
                continue
            tag = tag.strip()
            if not tag:
                continue
            key = normalize_tag(tag)
            if not key or key in seen_in_this_llm:
                continue
            seen_in_this_llm.add(key)
            entry = bucket.setdefault(
                key,
                {"votes": 0, "surface_forms": [], "voters": []},
            )
            entry["votes"] += 1
            if tag not in entry["surface_forms"]:
                entry["surface_forms"].append(tag)
            entry["voters"].append(llm)

    ordered = sorted(bucket.items(), key=lambda kv: (-kv[1]["votes"], kv[0]))
    canonical = [b["surface_forms"][0] for _, b in ordered if b["votes"] >= min_votes]
    return canonical, bucket


def run_consensus(min_votes: int) -> None:
    if not REASONING_DIR.exists() and not REASONING_MERGED_PATH.exists():
        raise SystemExit(
            f"No reasoning data at {REASONING_DIR} or {REASONING_MERGED_PATH}. "
            f"Run per-LLM passes first."
        )

    print(f"Loading reasoning from {REASONING_DIR} (per-LLM shards)...")
    reasoning = load_merged_reasoning()
    # Persist the merged view alongside the shards for inspection / archive.
    REASONING_MERGED_PATH.write_text(
        json.dumps(reasoning, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Loading shabads from {SGGS_PATH}...")
    shabads = json.loads(SGGS_PATH.read_text(encoding="utf-8"))
    by_sid = {str(s["banidb_shabad_id"]): s for s in shabads}

    # Coverage report — counted against the four LLMs we chose for consensus,
    # not every name the script knows about (e.g. gemma2:27b is permitted but
    # not currently part of the run).
    coverage = {llm: 0 for llm in CONSENSUS_LLMS}
    full_coverage = 0
    for sid, llm_results in reasoning.items():
        ok_llms = [llm for llm in CONSENSUS_LLMS if isinstance(llm_results.get(llm), dict) and "tags" in llm_results[llm]]
        for llm in ok_llms:
            coverage[llm] += 1
        if len(ok_llms) == len(CONSENSUS_LLMS):
            full_coverage += 1

    print("Per-LLM coverage:")
    for llm, n in coverage.items():
        print(f"  {llm:<22} {n}")
    print(f"  shabads with all {len(CONSENSUS_LLMS)} LLMs: {full_coverage}")
    print()

    print(f"Applying consensus rule (min_votes={min_votes})...")
    updated = 0
    skipped_partial = 0
    new_tag_counts: dict[str, int] = {}

    for sid, llm_results in reasoning.items():
        per_llm_tags = {
            llm: r.get("tags", []) for llm, r in llm_results.items()
            if isinstance(r, dict) and "tags" in r
        }
        if len(per_llm_tags) < min_votes:
            skipped_partial += 1
            continue

        canonical, _ = consensus_tags(per_llm_tags, min_votes=min_votes)
        if sid in by_sid:
            shabad = by_sid[sid]
            shabad["tags"] = canonical
            shabad["tags_source"] = "multi_llm_consensus_v1"

            # Take primary_theme/mood/brief_meaning from claude-sonnet-4-5 if available,
            # else qwen3:14b, else any. (Field-level, not shabad-level fallback.)
            for preferred in ("claude-sonnet-4-5", "qwen3:14b", "gemma2:27b", "deepseek-r1:14b"):
                r = llm_results.get(preferred)
                if isinstance(r, dict) and r.get("primary_theme"):
                    shabad["primary_theme"] = r.get("primary_theme", shabad.get("primary_theme", ""))
                    shabad["mood"] = r.get("mood", shabad.get("mood", ""))
                    shabad["brief_meaning"] = r.get("brief_meaning", shabad.get("brief_meaning", ""))
                    break

            updated += 1
            for tag in canonical:
                new_tag_counts[tag] = new_tag_counts.get(tag, 0) + 1

    print(f"  updated {updated} shabads; skipped {skipped_partial} with <{min_votes} LLM responses")

    # Build new tag vocabulary.
    print(f"\nWriting new {NEW_VOCAB_PATH.name}...")
    theme_tags = {
        tag: {"description": "", "gurbani_term": "", "count": count}
        for tag, count in sorted(new_tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    }
    NEW_VOCAB_PATH.write_text(
        json.dumps({"theme_tags": theme_tags, "mood_tags": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  {len(theme_tags)} consensus theme tags.")

    print(f"\nWriting updated {SGGS_PATH.name}...")
    SGGS_PATH.write_text(
        json.dumps(shabads, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  saved {len(shabads)} shabads.")

    # Top tags preview.
    print("\nTop 20 consensus tags:")
    for tag, count in sorted(new_tag_counts.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {count:>5}  {tag}")


# ---- CLI --------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--llm", help=f"Run a single-LLM tagging pass. One of: {', '.join(ALL_LLMS)}")
    p.add_argument("--consensus", action="store_true", help="Apply consensus rule and rebuild tags.")
    p.add_argument("--min-votes", type=int, default=2, help="Minimum LLM votes to keep a tag (default 2).")
    p.add_argument("--limit", type=int, default=None, help="Stop after N shabads (debug).")
    p.add_argument("--concurrency", type=int, default=8, help="Max concurrent in-flight calls.")
    p.add_argument("--save-every", type=int, default=50, help="Save reasoning file every N completions.")
    args = p.parse_args()

    if args.consensus and args.llm:
        raise SystemExit("Pass either --llm or --consensus, not both.")
    if not args.consensus and not args.llm:
        p.print_help()
        return

    if args.llm:
        run_pass(args.llm, args.concurrency, args.save_every, args.limit)
    else:
        run_consensus(args.min_votes)


if __name__ == "__main__":
    main()
