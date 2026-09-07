"""Embed every SGGS verse (tuk) individually for line-level matching.

The shabad collection (sggs_shabads) embeds a summary of each whole shabad:
theme, mood, brief meaning, rahao, translation. That vector answers "what is
this shabad about?" It cannot answer "where else does THIS thought appear?",
because a single striking line is averaged away into its shabad's gist.

This script builds the complementary collection (sggs_lines): one vector per
verse, embedded on the verse's English translation alone. No shabad-level theme
text is mixed in — doing so would pull every line of a shabad toward the same
point and collapse line matching back into shabad matching.

Source is the local BaniDB response cache (data/shabad_cache.db), so no network
calls: all 5,542 shabads are already cached with per-verse translations.

Run once (~10 min):
    python bootstrap/embed_lines.py

Rebuild after changing the line filter or the embedder.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import chromadb

import config
from database.vector_store import ShabadVectorStore

# A line needs enough words to carry meaning on its own. Formulaic closers
# ("||1||", "Nanak says") embed to noise and would pollute every result set.
MIN_ENGLISH_WORDS = 4


def extract_english(verse: dict) -> str:
    """Pull the best available English translation for a verse."""
    translation = verse.get("translation", {})
    en = translation.get("en", {}) if isinstance(translation, dict) else {}
    if not isinstance(en, dict):
        return ""
    return (en.get("bdb") or en.get("ms") or en.get("ssk") or "").strip()


def extract_gurmukhi(verse: dict) -> str:
    gurmukhi = verse.get("verse", {})
    return gurmukhi.get("unicode", "") if isinstance(gurmukhi, dict) else ""


def is_rahao_verse(verse: dict) -> bool:
    """Rahao ("pause") is the shabad's thesis line. Detected the same way the
    verses endpoint does it: the transliteration contains 'rahaau'."""
    translit = verse.get("transliteration", {})
    text = translit.get("en", "") if isinstance(translit, dict) else ""
    return "rahaau" in text.lower()


def collect_lines() -> list[dict]:
    """Read every cached shabad and flatten it into embeddable verse records."""
    db = sqlite3.connect(config.CACHE_DB_PATH)
    rows = db.execute("SELECT shabad_id, response FROM shabad_cache").fetchall()
    db.close()

    lines: list[dict] = []
    skipped_short = 0
    skipped_empty = 0

    for shabad_id, response in rows:
        try:
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            continue

        ang = 0
        info = data.get("shabadInfo") or {}
        if isinstance(info, dict):
            ang = info.get("pageNo") or 0

        for idx, verse in enumerate(data.get("verses", [])):
            english = extract_english(verse)
            if not english:
                skipped_empty += 1
                continue
            if len(english.split()) < MIN_ENGLISH_WORDS:
                skipped_short += 1
                continue

            lines.append({
                "id": f"{shabad_id}:{idx}",
                "shabad_id": str(shabad_id),
                "line_index": idx,
                "english": english,
                "gurmukhi": extract_gurmukhi(verse),
                "is_rahao": is_rahao_verse(verse),
                "ang": int(ang or 0),
            })

    print(f"  collected {len(lines)} lines from {len(rows)} shabads")
    print(f"  skipped {skipped_short} too-short, {skipped_empty} without translation")
    return lines


def embed_lines() -> None:
    print("Collecting verses from the BaniDB cache...")
    lines = collect_lines()
    if not lines:
        print("No lines found. Is data/shabad_cache.db populated?")
        return

    # Drop the old collection first with a bare client: ChromaDB pins an
    # embedding-function config per collection, so a rebuild must start clean.
    print(f"\nDropping old collection ({config.SGGS_LINES_COLLECTION_NAME})...")
    bare = chromadb.PersistentClient(path=config.CHROMA_DB_PATH)
    try:
        bare.delete_collection(config.SGGS_LINES_COLLECTION_NAME)
        print("  dropped.")
    except Exception as err:  # noqa: BLE001 — chromadb raises varied not-found types
        print(f"  nothing to drop ({type(err).__name__}).")

    print(f"\nEmbedding {len(lines)} lines...")
    store = ShabadVectorStore(collection_name=config.SGGS_LINES_COLLECTION_NAME)
    store.add_lines(lines)

    rahao = sum(1 for ln in lines if ln["is_rahao"])
    shabads = len({ln["shabad_id"] for ln in lines})
    print(f"\nDone. {store.get_count()} lines across {shabads} shabads ({rahao} rahao lines).")


if __name__ == "__main__":
    from bootstrap.build_guard import require_build_target
    require_build_target(legacy=False)
    embed_lines()
