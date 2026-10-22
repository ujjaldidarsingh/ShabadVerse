"""Read scripture and search locally from the preserved BaniDB snapshot."""

import json
import re
import sqlite3
from contextlib import closing
import unicodedata
from functools import lru_cache
from pathlib import Path

import config

# The rahao marker follows a ॥, often numbered (॥੧॥ ਰਹਾਉ ॥). The word ਰਹਾਉ alone
# can also mean "remain" (ਗੁਰਮਤਿ ਸਾਚਿ ਰਹਾਉ), so a bare match is not enough.
RAHAO_MARK = re.compile(r"॥\s*(?:[੦-੯0-9]+\s*॥)?\s*ਰਹਾਉ(?:\s+ਦੂਜਾ)?\s*॥")
STANZA_END = re.compile(r"॥\s*[੦-੯0-9]+\s*॥\s*$")
HEADING = re.compile(r"ੴ|ਮਹਲਾ|ਮਃ|ਘਰੁ\s*[੦-੯]|^\s*(?:ਸਲੋਕ|ਪਉੜੀ|ਛੰਤੁ|ਡਖਣਾ|ਰਾਗੁ)")
# Titles HEADING misses: Bhagat and Vaar titles, composition labels, and raag or
# set labels with a bare number (ਗਉੜੀ ਮਾਲਾ ੫ ॥, ਛਕਾ ੧ ॥). Across all 60,403 verses
# these and UNMARKED add 132 headings and no verses.
TITLE = re.compile(
    r"ਬਾਣੀ ਭਗਤਾਂ? ਕੀ|ਬਾਣੀ ਭਗਤ \S+ ਜੀ|ਕੀ ਵਾਰ|(?:ਦੁ|ਤਿ|ਚਉ|ਪੰਚ|ਛਿ|ਅਸਟ)ਪਦੇ|(?:ਇਕ|ਦੁ|ਤਿ|ਚਾਰ|ਚਉ)ਤੁਕੇ"
    r"|^[^੦-੯]*\s[੦-੯]+\s*॥?\s*$"
    r"|(?:ਕਬੀਰ|ਨਾਮਦੇ[ਉਵ]|ਰਵਿਦਾਸ|ਧੰਨੇ|ਬੇਣੀ|ਤ੍ਰਿਲੋਚਨ|ਸਧਨੇ|ਸੈਣ|ਪੀਪਾ|ਭੀਖਨ|ਜੈਦੇਵ|ਸੂਰਦਾਸ|ਪਰਮਾਨੰਦ|ਰਾਮਾਨੰਦ|ਫਰੀਦ)\s+ਜੀਉ?(?=\s|॥|$)"
)
# A line without a verse mark is a title when it opens the shabad (ਰਾਮਕਲੀ ਸਦੁ);
# further in, a few verses lack the mark.
UNMARKED = re.compile(r"^[^॥]+$")
TITLE_LINES = 3
# A rahao spans at most this many verses before the one carrying its marker.
RAHAO_LOOKBACK = 3


def is_heading(gurmukhi, index=None):
    """Invocations, raag and composition headings and titles, not verses of the shabad.

    Pass the verse index when it is known: a line without a verse mark counts as a
    title only among the first lines of a shabad.
    """
    text = gurmukhi or ""
    if HEADING.search(text) or TITLE.search(text):
        return True
    return index is not None and index < TITLE_LINES and bool(UNMARKED.match(text))


def rahao_span(verses):
    """Indices of every verse in a shabad's rahao, given its Gurmukhi verses in order.

    Each verse carrying the marker, plus the verses before it back to the previous
    numbered stanza end or heading, because a rahao often spans two or more verses.
    """
    span = set()
    for end in (i for i, text in enumerate(verses) if RAHAO_MARK.search(text or "")):
        span.add(end)
        j = end - 1
        while j >= 0 and end - j <= RAHAO_LOOKBACK and j not in span:
            if STANZA_END.search(verses[j] or "") or is_heading(verses[j], j):
                break
            span.add(j)
            j -= 1
    return span


def normalize_initials(text):
    """Search keys only: independent vowels share their Gurmukhi carrier."""
    carriers = str.maketrans(
        {
            "ਆ": "ਅ",
            "ਐ": "ਅ",
            "ਔ": "ਅ",
            "ਇ": "ੲ",
            "ਈ": "ੲ",
            "ਏ": "ੲ",
            "ਉ": "ੳ",
            "ਊ": "ੳ",
            "ਓ": "ੳ",
        }
    )
    text = unicodedata.normalize("NFC", text).translate(carriers)
    return "".join(c for c in text if unicodedata.category(c).startswith("L"))


def first_letters(text):
    """Ignore punctuation and combining marks; retain the first letter per word."""
    words = unicodedata.normalize("NFC", text).split()
    return normalize_initials(
        "".join(
            next((c for c in word if unicodedata.category(c).startswith("L")), "")
            for word in words
        )
    )


def verse_record(verse, index):
    translations = (verse.get("translation") or {}).get("en") or {}
    if not isinstance(translations, dict):
        translations = {}
    provider = next((p for p in ("bdb", "ms", "ssk") if translations.get(p)), None)
    transliteration = (verse.get("transliteration") or {}).get("en", "")
    return {
        "index": index,
        "verse_id": verse.get("verseId"),
        "gurmukhi": (verse.get("verse") or {}).get("unicode", ""),
        "english": translations.get(provider, ""),
        "translation_source": provider,
        "transliteration": transliteration,
        "is_rahao": "rahaau" in transliteration.lower(),
    }


@lru_cache(maxsize=128)
def shabad(shabad_id):
    path = Path(config.CACHE_DB_PATH).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute(
            "SELECT response FROM shabad_cache WHERE shabad_id = ?", (str(shabad_id),)
        ).fetchone()
    if not row:
        return None
    raw = json.loads(row[0])
    info = raw.get("shabadInfo") or {}
    verses = [verse_record(v, i) for i, v in enumerate(raw.get("verses", []))]
    return {
        "banidb_shabad_id": str(shabad_id),
        "verses": verses,
        "rahao_index": next((v["index"] for v in verses if v["is_rahao"]), -1),
        "raag": (info.get("raag") or {}).get("english", ""),
        "writer": (info.get("writer") or {}).get("english", ""),
        "ang": info.get("pageNo") or 0,
        "source": "BaniDB cached snapshot",
    }


@lru_cache(maxsize=1)
def search_index():
    """Compact index, built once without holding the full raw cache in memory."""
    entries = []
    path = Path(config.CACHE_DB_PATH).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        for sid, response in db.execute(
            "SELECT shabad_id, response FROM shabad_cache ORDER BY shabad_id"
        ):
            for index, verse in enumerate(json.loads(response).get("verses", [])):
                gurmukhi = (verse.get("verse") or {}).get("unicode", "")
                entries.append((str(sid), index, first_letters(gurmukhi)))
    return entries


def search(query, searchtype=0, limit=30):
    needle = normalize_initials(query)
    if len(needle) < 2:
        return []
    results, seen = [], set()
    for sid, index, initials in search_index():
        if sid in seen:
            continue
        matches = initials.startswith(needle) if searchtype == 0 else needle in initials
        if not matches:
            continue
        data = shabad(sid)
        verse = data["verses"][index]
        results.append(
            {
                "banidb_shabad_id": sid,
                "line_index": index,
                "title_gurmukhi": verse["gurmukhi"],
                "title_transliteration": verse["transliteration"],
                "first_line_translation": verse["english"],
                "translation_source": verse["translation_source"],
                "ang_number": data["ang"],
                "raag": data["raag"],
                "writer": data["writer"],
            }
        )
        seen.add(sid)
        if len(results) >= limit:
            break
    return results
