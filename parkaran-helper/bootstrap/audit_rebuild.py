"""Audit the post-rebuild SGGS tags against the pre-rebuild snapshot.

Produces data/rebuild_audit.md, a markdown report covering:

  1. Taxonomy diff: total tags, top tags, what got added/dropped
  2. AK source field validation: are all 2,078 AK shabads still flagged?
  3. Per-LLM consensus stats: how many shabads has each LLM tagged
  4. Sample comparison: 20 randomly-chosen shabads, before-vs-after tags side by side
  5. Hukam attribution check: shabads with Hukam-related tags before AND after,
     to spot obvious miscalls Harsimran's gist mentioned
  6. Singleton-tag survivors: tags that only one LLM voted for and got dropped
     (sanity check that consensus is actually filtering noise, not killing signal)

Run after Phase B.5 final consensus and before Phase F deploy.

Usage:
    python bootstrap/audit_rebuild.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config

DATA_DIR = Path(config.DATA_DIR)
PRE_SNAPSHOT_PATH = DATA_DIR / "sggs_tags_pre_rebuild.json"
SGGS_PATH = Path(config.SGGS_DATA_PATH)
SOURCES_PATH = DATA_DIR / "sggs_sources.json"
REASONING_DIR = DATA_DIR / "tag_reasoning"
AUDIT_PATH = DATA_DIR / "rebuild_audit.md"

CONSENSUS_LLMS = ["qwen3:14b", "deepseek-r1:14b", "llama3.1:8b", "claude-sonnet-4-5"]


def _load_shard(name: str) -> dict:
    p = REASONING_DIR / f"{name.replace(':', '_')}.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def section_taxonomy_diff(pre: dict, shabads: list[dict]) -> str:
    """Compare old vs new tag taxonomy at the corpus level."""
    old_counts: dict[str, int] = {}
    for sid_data in pre.values():
        for tag in sid_data.get("tags", []):
            old_counts[tag] = old_counts.get(tag, 0) + 1

    new_counts: dict[str, int] = {}
    for s in shabads:
        for tag in s.get("tags", []) or []:
            new_counts[tag] = new_counts.get(tag, 0) + 1

    old_set = set(old_counts.keys())
    new_set = set(new_counts.keys())

    added = sorted(new_set - old_set, key=lambda t: -new_counts.get(t, 0))
    dropped = sorted(old_set - new_set, key=lambda t: -old_counts.get(t, 0))

    out = ["## 1. Taxonomy diff", ""]
    out.append(f"- Pre-rebuild: **{len(old_set)} unique tags**")
    out.append(f"- Post-rebuild: **{len(new_set)} unique tags**")
    out.append(f"- Added: **{len(added)}**, Dropped: **{len(dropped)}**")
    out.append("")
    out.append("### Top 25 post-rebuild tags")
    out.append("| count | tag |")
    out.append("|---:|---|")
    for tag, c in sorted(new_counts.items(), key=lambda kv: -kv[1])[:25]:
        out.append(f"| {c} | {tag} |")
    out.append("")
    out.append(f"### Sample of dropped tags (top 30 by old count)")
    out.append("Tags the consensus rejected — most should be noise duplicates")
    out.append("(e.g. 'Bhakti (Devotional Love)' merging into 'Bhakti').")
    out.append("")
    out.append("| pre count | dropped tag |")
    out.append("|---:|---|")
    for tag in dropped[:30]:
        out.append(f"| {old_counts[tag]} | {tag} |")
    out.append("")
    return "\n".join(out)


def section_ak_validation(sources: dict, shabads: list[dict]) -> str:
    """Confirm AK source field is intact and matches our index."""
    by_sid = {str(s["banidb_shabad_id"]): s for s in shabads}
    ak_sids = {sid for sid, fields in sources.items() if fields.get("amrit_keertan")}
    missing = [sid for sid in ak_sids if sid not in by_sid]

    out = ["## 2. AK source validation", ""]
    out.append(f"- AK shabads in sources: **{len(ak_sids)}**")
    out.append(f"- AK shabads present in metadata: **{len(ak_sids) - len(missing)}**")
    if missing:
        out.append(f"- ⚠️ Missing in metadata: {missing[:10]}")
    else:
        out.append("- ✅ All AK shabads accounted for in metadata.")
    out.append("")
    return "\n".join(out)


def section_llm_coverage() -> str:
    """Per-LLM coverage report from the per-LLM shards."""
    out = ["## 3. Per-LLM coverage", "", "| LLM | tagged | error rows |", "|---|---:|---:|"]
    for llm in CONSENSUS_LLMS:
        shard = _load_shard(llm)
        ok = sum(1 for r in shard.values() if isinstance(r, dict) and "tags" in r and not r.get("error"))
        err = sum(1 for r in shard.values() if isinstance(r, dict) and r.get("error"))
        out.append(f"| {llm} | {ok} | {err} |")
    out.append("")
    return "\n".join(out)


def section_sample_diff(pre: dict, shabads: list[dict], n: int = 20, seed: int = 42) -> str:
    """Random sample of N shabads with before/after tags side by side."""
    by_sid = {str(s["banidb_shabad_id"]): s for s in shabads}
    rng = random.Random(seed)
    sample_sids = rng.sample(list(by_sid.keys()), min(n, len(by_sid)))

    out = ["## 4. Random sample (20 shabads)", ""]
    for sid in sample_sids:
        s = by_sid[sid]
        old = pre.get(sid, {})
        title = (s.get("display_name") or s.get("gurmukhi_text", "")[:40] or "?").strip()
        ang = s.get("ang_number", "?")
        out.append(f"### shabad {sid} (ang {ang})")
        out.append(f"_{title}_")
        out.append("")
        out.append(f"- **before**: theme=`{old.get('primary_theme','')}`, tags=`{old.get('tags', [])}`")
        out.append(f"- **after**:  theme=`{s.get('primary_theme','')}`, tags=`{s.get('tags', [])}`")
        out.append("")
    return "\n".join(out)


def section_hukam_check(pre: dict, shabads: list[dict]) -> str:
    """Surface shabads tagged with Hukam (or related) before AND after.

    Lets us eyeball the Hukam-misattribution example Harsimran flagged in his
    gist — if any shabad in the comparison has Hukam in 'before' but loses it
    or gains it in 'after', it's worth a manual look.
    """
    by_sid = {str(s["banidb_shabad_id"]): s for s in shabads}
    hukam_aliases = {"hukam", "divine will", "divine command", "command", "will"}

    def has_hukam(tag_list: list[str]) -> bool:
        return any(t.lower() in hukam_aliases or "hukam" in t.lower() for t in tag_list or [])

    flipped: list[tuple[str, dict, dict]] = []
    for sid, s in by_sid.items():
        old_tags = pre.get(sid, {}).get("tags", [])
        new_tags = s.get("tags", [])
        if has_hukam(old_tags) != has_hukam(new_tags):
            flipped.append((sid, old_tags, new_tags))

    out = ["## 5. Hukam attribution flips", ""]
    out.append(f"Shabads where 'Hukam'-family tags appeared in one taxonomy but not the other: **{len(flipped)}**")
    out.append("")
    out.append("First 25 flips for manual review:")
    out.append("")
    out.append("| shabad | before | after |")
    out.append("|---|---|---|")
    for sid, old, new in flipped[:25]:
        out.append(f"| {sid} | `{old}` | `{new}` |")
    out.append("")
    return "\n".join(out)


def section_consensus_drops() -> str:
    """How many singleton tags did consensus drop, and which ones top the list?"""
    bucket: dict[str, dict] = {}
    for llm in CONSENSUS_LLMS:
        shard = _load_shard(llm)
        for sid, r in shard.items():
            if not isinstance(r, dict) or "tags" not in r:
                continue
            for tag in r.get("tags", []) or []:
                if not isinstance(tag, str):
                    continue
                key = tag.lower().strip()
                if not key:
                    continue
                entry = bucket.setdefault(key, {"surface": tag, "voters": set(), "shabads": set()})
                entry["voters"].add(llm)
                entry["shabads"].add(sid)

    singletons = [
        (b["surface"], len(b["shabads"]))
        for b in bucket.values()
        if len(b["voters"]) == 1
    ]
    singletons.sort(key=lambda kv: -kv[1])

    out = ["## 6. Consensus singletons (dropped tags)", ""]
    out.append(f"Tags only one LLM voted for (filtered out by min_votes=2): **{len(singletons)}**")
    out.append("")
    out.append("Top 30 by shabad count (these are the noisiest single-voice tags):")
    out.append("")
    out.append("| shabads | tag |")
    out.append("|---:|---|")
    for tag, n in singletons[:30]:
        out.append(f"| {n} | {tag} |")
    out.append("")
    return "\n".join(out)


def main() -> None:
    if not PRE_SNAPSHOT_PATH.exists():
        sys.exit(f"Pre-rebuild snapshot missing at {PRE_SNAPSHOT_PATH}. Capture before running consensus.")
    if not SGGS_PATH.exists():
        sys.exit(f"SGGS data missing at {SGGS_PATH}.")

    pre = json.loads(PRE_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    shabads = json.loads(SGGS_PATH.read_text(encoding="utf-8"))
    sources = (
        json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
        if SOURCES_PATH.exists()
        else {}
    )

    parts = [
        f"# ShabadVerse rebuild audit\n\nGenerated by `bootstrap/audit_rebuild.py`.\n",
        section_taxonomy_diff(pre, shabads),
        section_ak_validation(sources, shabads),
        section_llm_coverage(),
        section_sample_diff(pre, shabads),
        section_hukam_check(pre, shabads),
        section_consensus_drops(),
    ]

    AUDIT_PATH.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {AUDIT_PATH} ({AUDIT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
