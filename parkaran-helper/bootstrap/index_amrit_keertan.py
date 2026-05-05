"""Index Amrit Keertan shabads via BaniDB.

Pulls the AK index from BaniDB's /v2/amritkeertan/index endpoint and produces
two artifacts:

1. data/sggs_sources.json — {shabad_id: {amrit_keertan: bool}}
   Drop-in metadata layer that other tools (build_graph, graph_api) read.
2. data/amrit_keertan_index.json — the raw AK index for reference and future
   features (e.g. browsing AK by chapter, AK-aware search ordering).

The AK index has ~2,675 entries. Each entry maps an AK chapter (HeaderID)
to a SGGS shabad (ShabadID). Multiple AK entries can point to the same SGGS
shabad (different verses of one shabad appearing in different AK chapters);
we deduplicate at the shabad level.

This script is idempotent — running it again refreshes both files in place.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

AK_INDEX_URL = f"{config.BANIDB_BASE_URL}/amritkeertan/index"
AK_INDEX_PATH = Path(config.DATA_DIR) / "amrit_keertan_index.json"
SOURCES_PATH = Path(config.DATA_DIR) / "sggs_sources.json"


def fetch_ak_index(session: requests.Session, max_retries: int = 4) -> list[dict]:
    """Fetch the full AK index with backoff on rate limits or transient errors."""
    for attempt in range(max_retries):
        try:
            resp = session.get(AK_INDEX_URL, timeout=30)
            if resp.status_code == 429:
                wait = 5 * (2**attempt)
                print(f"  Rate limited, waiting {wait}s (attempt {attempt + 1})...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            payload = resp.json()
            entries = payload.get("index", [])
            if not entries:
                raise ValueError("AK index payload missing 'index' array")
            return entries
        except (requests.RequestException, ValueError) as err:
            if attempt == max_retries - 1:
                raise
            wait = 2 * (2**attempt)
            print(f"  Fetch error: {err}. Retrying in {wait}s...")
            time.sleep(wait)
    return []


def build_shabad_map(entries: list[dict]) -> dict[str, dict]:
    """Group AK entries by SGGS shabad ID. Returns {shabad_id: {ak_chapters, ak_entry_count}}.

    The AK index spans six sources (G, D, B, N, R, S). We only index AK entries
    whose source is SGGS (G) since that's the corpus this app covers — Dasam Bani,
    Bhai Gurdas Vaaran, etc. would be off-corpus and produce dangling references.

    Each shabad gets:
      - amrit_keertan: True (membership flag)
      - ak_chapters: sorted list of HeaderIDs the shabad appears in
      - ak_entry_count: how many AK index lines reference this shabad
    """
    by_shabad: dict[str, dict] = {}
    for entry in entries:
        if entry.get("SourceID") != config.BANIDB_SOURCE:
            continue
        sid = entry.get("ShabadID")
        header_id = entry.get("HeaderID")
        if sid is None or header_id is None:
            continue
        sid_str = str(sid)
        bucket = by_shabad.setdefault(
            sid_str,
            {
                "amrit_keertan": True,
                "ak_chapters": set(),
                "ak_entry_count": 0,
            },
        )
        bucket["ak_chapters"].add(int(header_id))
        bucket["ak_entry_count"] += 1

    # Convert sets to sorted lists for JSON serialization.
    for sid, bucket in by_shabad.items():
        bucket["ak_chapters"] = sorted(bucket["ak_chapters"])

    return by_shabad


def merge_into_sources(ak_map: dict[str, dict]) -> dict[str, dict]:
    """Read existing sggs_sources.json (if any) and merge AK flags in.

    Preserves any future flags (e.g., bahu_shabdi) that other indexers add.
    """
    existing: dict[str, dict] = {}
    if SOURCES_PATH.exists():
        try:
            existing = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            print(f"  Warning: existing sources file unreadable ({err}); starting fresh.")
            existing = {}

    # Reset AK fields for every SGGS shabad first so removed entries don't linger.
    for sid in list(existing.keys()):
        existing[sid].pop("amrit_keertan", None)
        existing[sid].pop("ak_chapters", None)
        existing[sid].pop("ak_entry_count", None)
        # Drop the row entirely if it has no remaining flags.
        if not existing[sid]:
            del existing[sid]

    # Apply new AK data.
    for sid, fields in ak_map.items():
        existing.setdefault(sid, {}).update(fields)

    return existing


def index_amrit_keertan() -> None:
    print("Fetching Amrit Keertan index from BaniDB...")
    session = requests.Session()
    entries = fetch_ak_index(session)
    print(f"  Got {len(entries)} AK index entries.")

    print("Saving raw AK index...")
    AK_INDEX_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    size_mb = AK_INDEX_PATH.stat().st_size / 1_000_000
    print(f"  Wrote {AK_INDEX_PATH.name} ({size_mb:.1f} MB)")

    print("Building shabad-level AK map...")
    ak_map = build_shabad_map(entries)
    print(f"  {len(ak_map)} unique SGGS shabads referenced in AK.")

    print("Merging into sggs_sources.json...")
    sources = merge_into_sources(ak_map)
    SOURCES_PATH.write_text(
        json.dumps(sources, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  Wrote {SOURCES_PATH.name} with {len(sources)} shabads.")

    # Quick sanity: chapter coverage.
    chapter_set = set()
    for fields in sources.values():
        chapter_set.update(fields.get("ak_chapters", []))
    print(f"\nDone. AK chapters covered: {len(chapter_set)}")
    print(f"Total SGGS shabads tagged AK: {sum(1 for f in sources.values() if f.get('amrit_keertan'))}")


if __name__ == "__main__":
    index_amrit_keertan()
