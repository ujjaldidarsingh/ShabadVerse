"""Meaning search: local lists fused by rank, optionally reordered by Claude Haiku 5.5.

Five local lists, each one shabad per entry with the verse that matched:
  line     Punjabi typed in English letters, compared with each verse's BaniDB
           transliteration by consonant skeleton, so "tati vao" meets "taatee vaau"
  words    Gurmukhi words, found at the start of words in each verse
  concept  concept names in English letters or Gurmukhi, through the concept weights
  verse    verse translations closest in meaning (sggs_lines)
  shabad   machine summaries closest in meaning (sggs_shabads), without the
           summaries that only report missing text
Reciprocal rank fusion merges them. A result that carries a verse opens line
matching from that verse.

With ANTHROPIC_API_KEY set and SHABADVERSE_RERANK=1, Claude Haiku 5.5 can reorder
the fused candidates and say briefly why each fits. A limit, timeout, refusal or
API error leaves the local order in place.
"""

import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
import unicodedata
from collections import OrderedDict, defaultdict, deque
from contextlib import closing
from functools import lru_cache
from pathlib import Path

from flask import jsonify, request

import config
from api.graph_api import (
    _FINAL_NASAL,
    _FINAL_VOWEL,
    _PUNCTUATION,
    _get_concepts,
    _get_graph,
    _get_lines_vector_store,
    _get_sggs_lookup,
    _get_sggs_vector_store,
    _get_tag_vocab,
    graph_bp,
)
from database import corpus

log = logging.getLogger(__name__)

MAX_QUERY = 300
MAX_RESULTS = 25
POOL = 30  # entries kept per list, and fused candidates offered for reordering
VERSE_FETCH = 120  # verses fetched by meaning before keeping each shabad's best
RRF_K = 60
# Typed words are the strongest evidence of what someone wants. Concept names
# count as strongly when the whole query is concept names.
WEIGHTS = {"line": 3.0, "words": 3.0, "concept": 1.0, "verse": 1.0, "shabad": 0.7}
NAMED_CONCEPT_WEIGHT = 3.0
TYPED = ("line", "words")
EVIDENCE_ORDER = ("line", "words", "verse", "concept", "shabad")
# A typed line must share this many consonants in order with a verse, and cover
# this share of what was typed, before the verse counts as the line.
MIN_ROMAN_LETTERS = 5
ROMAN_COVERAGE = 0.5
FOUND_LINE = 0.8  # share of a typed line a verse must hold to stand in for the query
# Titles that database.corpus.HEADING misses: Bhagat and Vaar titles, composition
# labels and raag lines with a bare number (ਗਉੜੀ ਮਾਲਾ ੫). Their English is a run of
# names, which the embedding model matches to any Punjabi typed in English letters.
TITLE = re.compile(
    r"ਬਾਣੀ ਭਗਤਾਂ? ਕੀ|ਬਾਣੀ ਭਗਤ \S+ ਜੀ|ਕੀ ਵਾਰ|(?:ਦੁ|ਤਿ|ਚਉ|ਪੰਚ|ਛਿ|ਅਸਟ)ਪਦੇ|(?:ਇਕ|ਦੁ|ਤਿ|ਚਾਰ|ਚਉ)ਤੁਕੇ"
    r"|^[^੦-੯]*\s[੦-੯]+\s*॥?\s*$"
    r"|(?:ਕਬੀਰ|ਨਾਮਦੇ[ਉਵ]|ਰਵਿਦਾਸ|ਧੰਨੇ|ਬੇਣੀ|ਤ੍ਰਿਲੋਚਨ|ਸਧਨੇ|ਸੈਣ|ਪੀਪਾ|ਭੀਖਨ|ਜੈਦੇਵ|ਸੂਰਦਾਸ|ਪਰਮਾਨੰਦ|ਰਾਮਾਨੰਦ|ਫਰੀਦ)\s+ਜੀਉ?(?=\s|॥|$)"
)
UNMARKED = re.compile(r"^[^॥]*$")  # no verse mark; a title when it opens the shabad
TITLE_LINES = 3
# Machine summaries that say nothing about the shabad.
EMPTY_SUMMARY = re.compile(
    r"(?i)incomplete|only the header|header provided|without verse content|no verse content|cannot be analy[sz]ed"
)
GURMUKHI = re.compile(r"[਀-੿]")
LATIN_WORD = re.compile(r"[a-z]+")
LATIN_MARKS = re.compile(r"[()'’]")
# BaniDB writes nasals as (n) and long vowels doubled; people type neither
# consistently. Both sides drop vowels and every n after a word's first letter, and
# merge spellings of one letter, so spellings of the same word meet.
DIGRAPHS = (
    ("chh", "c"),
    ("sh", "s"),
    ("kh", "k"),
    ("gh", "g"),
    ("ch", "c"),
    ("jh", "j"),
    ("th", "t"),
    ("dh", "d"),
    ("ph", "p"),
    ("bh", "b"),
    ("f", "p"),
    ("w", "v"),
    ("z", "j"),
    ("q", "k"),
)
VOWELS = re.compile(r"[aeiouy]")
VOWEL_WORD = "·"  # skeleton of a word with no consonants
FILLER_WORDS = frozenset({"and", "or", "te", "ate"})
# ponytail: a hand-kept list of common English-letter spellings. Move it into the
# curated vocabulary once Ujjal has reviewed spellings for each concept.
ROMAN_SPELLINGS = {
    "karodh": "krodh",
    "moha": "moh",
    "hankar": "ahankar",
    "ahankaar": "ahankar",
    "hankaar": "ahankar",
    "haume": "haumai",
    "haumay": "haumai",
    "houmai": "haumai",
    "homai": "haumai",
    "ninda": "nindaa",
    "nindya": "nindaa",
    "nindiya": "nindaa",
    "trisna": "trishna",
    "bhram": "bharam",
    "santosh": "santokh",
    "dayal": "Daya (divine)",
    "dayaal": "Daya (divine)",
    "sachu": "sach",
    "pyar": "prem",
    "pyaar": "prem",
    "piaar": "prem",
    "naamu": "naam",
    "simar": "simran",
    "simaran": "simran",
    "simrin": "simran",
    "sewa": "seva",
    "satsang": "sangat",
    "satsangat": "sangat",
    "sadhsangat": "sangat",
    "sadh sangat": "sangat",
    "keertan": "kirtan",
    "ardaas": "ardas",
    "daanu": "daan",
    "veechar": "vichar",
    "vichaar": "vichar",
    "hukum": "hukam",
    "hukm": "hukam",
    "maaya": "maya",
    "mukat": "mukti",
    "moksh": "mukti",
    "janam": "janam maran",
    "maran": "janam maran",
    "kripa": "kirpa",
    "nadar": "kirpa",
    "sabad": "shabad",
    "shabd": "shabad",
    "satgur": "satguru",
    "satigur": "satguru",
    "jyot": "jot",
    "joti": "jot",
    "bhavjal": "bhaujal",
    "bhavsagar": "bhaujal",
    "sehaj": "sahaj",
    "bhakti": "bhagti",
    "jaati": "jaat",
    "jati": "jaat",
    "teerath": "tirath",
    "vismaad": "vismad",
    "virha": "birha",
    "birah": "birha",
    "vichhora": "birha",
    "vichhoda": "birha",
    "chardikala": "chardi kala",
    "charhdi kala": "chardi kala",
    "nimrta": "nimrata",
    "garibi": "nimrata",
    "gareebi": "nimrata",
}

RERANK_MODEL = "claude-haiku-5-5"
RERANK_KEEP = 10
RERANK_TIMEOUT = 10.0  # seconds; the local order is already on screen
RERANK_DAILY_CAP = int(os.getenv("SHABADVERSE_RERANK_DAILY_CAP", "2000"))
VISITOR_LIMIT, VISITOR_WINDOW = 30, 600  # reorderings per visitor per ten minutes
VISITORS_TRACKED = 5000  # past this, visitors idle for a whole window are forgotten
DAY = 86400
REASON_CHARS = 160
ORDER_CACHE = 512
RERANK_SYSTEM = (
    "You order search results for ShabadVerse, which helps people find shabads in Sri Guru Granth Sahib. "
    "The seeker may type English, Punjabi in English letters, or Gurmukhi: a remembered line, a theme, "
    "or a concept. Each candidate shows the verse that matched, with its BaniDB English translation and "
    "transliteration, and the shabad's rahao when it has one. Return the candidates that fit the search, "
    "best first, at most 10, and leave out those that do not. A candidate holding the line the seeker typed "
    "comes first. For each, give a reason of at most 15 words that points to its verse. Use only the given ids."
)
RERANK_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["id", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}
BADGES = {
    "line": "MATCHED LINE",
    "words": "MATCHED WORDS",
    "concept": "BY CONCEPT",
    "verse": "BY MEANING",
    "shabad": "BY SUMMARY",
}

_verse_index = None
_verse_lock = threading.Lock()
_limits = threading.Lock()
_calls: deque = deque()
_visitors: dict = defaultdict(deque)
_orders: OrderedDict = OrderedDict()


def normalize_query(text):
    return " ".join(unicodedata.normalize("NFC", text or "").split())[:MAX_QUERY]


def roman_words(text):
    return LATIN_WORD.findall(LATIN_MARKS.sub("", text.lower()))


def skeleton(word):
    """Consonants of an English-letter word: taatee and tati both give t."""
    w = word.lower()
    for pair, letter in DIGRAPHS:
        w = w.replace(pair, letter)
    w = VOWELS.sub("", w[:1] + w[1:].replace("n", ""))
    return re.sub(r"(.)\1+", r"\1", w) or VOWEL_WORD


def _letters(skel):
    return 0 if skel == VOWEL_WORD else len(skel)


def roman_needle(text):
    return " " + " ".join(skeleton(w) for w in roman_words(text)) + " "


def stem(token):
    return _FINAL_VOWEL.sub("", _FINAL_NASAL.sub("", token))


def gurmukhi_stems(text):
    tokens = _PUNCTUATION.sub(" ", unicodedata.normalize("NFC", text)).split()
    return [stem(t) for t in tokens if GURMUKHI.search(t)]


def is_title(gurmukhi, index):
    """Headings and titles, which are never search results."""
    return (
        corpus.is_heading(gurmukhi)
        or bool(TITLE.search(gurmukhi))
        or (index < TITLE_LINES and bool(UNMARKED.match(gurmukhi)))
    )


def _build_verse_index():
    ids, rows = set(_get_graph()["metadata"]), []
    path = Path(config.CACHE_DB_PATH).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        for sid, response in db.execute("SELECT shabad_id, response FROM shabad_cache"):
            if str(sid) not in ids:
                continue
            for idx, verse in enumerate(json.loads(response).get("verses", [])):
                record = corpus.verse_record(verse, idx)
                gurmukhi = unicodedata.normalize("NFC", record["gurmukhi"])
                if gurmukhi and not is_title(gurmukhi, idx):
                    skel = roman_needle(record["transliteration"])
                    rows.append((str(sid), idx, " " + gurmukhi, skel))
    return tuple(rows)


def _verses():
    """(shabad, verse index, Gurmukhi, transliteration skeleton) for every verse but titles.

    Only the BaniDB cache holds each verse's transliteration, so the index is read
    from it once, on first use or at warm-up.
    """
    global _verse_index
    if _verse_index is None:
        with _verse_lock:
            if _verse_index is None:
                _verse_index = _build_verse_index()
    return _verse_index


def warm():
    """Build the verse index and open both vector collections before the first search."""
    try:
        _verses()
        candidates("warm up")
    except (OSError, RuntimeError, sqlite3.Error) as error:
        log.warning("Search warm-up failed: %s", error)


def _longest_run(words, present, skel):
    """Consonants in the longest run of typed words that a verse holds in order."""
    best, i = 0, 0
    while i < len(present):
        if not present[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(present) and present[j + 1]:
            j += 1
        run = words[i : j + 2]
        if " " + " ".join(run) + " " in skel:
            best = max(best, sum(map(_letters, run)))
        else:
            best = max(
                best,
                max(
                    _letters(words[k]) + _letters(words[k + 1]) for k in range(i, j + 1)
                ),
            )
        i = j + 1
    return best


def _best_per_shabad(hits):
    seen, out = set(), []
    for hit in hits:
        if hit[0] not in seen:
            seen.add(hit[0])
            out.append(hit)
    return out


def roman_lines(query):
    """Verses holding most of a line typed in English letters, in order."""
    words = [skeleton(w) for w in roman_words(query)]
    total = sum(map(_letters, words))
    if len(words) < 2 or total < MIN_ROMAN_LETTERS:
        return []
    pairs = [f" {a} {b} " for a, b in zip(words, words[1:])]
    hits = []
    for sid, idx, _, skel in _verses():
        present = [pair in skel for pair in pairs]
        if True not in present:
            continue
        letters = _longest_run(words, present, skel)
        if letters >= MIN_ROMAN_LETTERS and letters >= ROMAN_COVERAGE * total:
            hits.append((sid, idx, round(letters / total, 3), len(skel)))
    hits.sort(key=lambda h: (-h[2], h[3], int(h[0])))
    return [(sid, idx, score) for sid, idx, score, _ in _best_per_shabad(hits)[:POOL]]


def gurmukhi_words(query):
    """Shabads with verses holding at least half the typed Gurmukhi words.

    More of the words in one verse ranks first, then shabads that return to them
    in more verses.
    """
    stems = list(dict.fromkeys(s for s in gurmukhi_stems(query) if len(s) >= 2))
    if not stems:
        return []
    needles = [" " + s for s in stems]
    best = {}
    for sid, idx, text, _ in _verses():
        found = sum(n in text for n in needles)
        if not found:
            continue
        entry = best.setdefault(sid, [0, idx, 0])
        entry[2] += 1
        if found > entry[0]:
            entry[0], entry[1] = found, idx
    need = math.ceil(len(stems) / 2)
    ranked = sorted(
        (s for s, e in best.items() if e[0] >= need),
        key=lambda s: (-best[s][0], -best[s][2], int(s)),
    )
    return [
        (sid, best[sid][1], round(best[sid][0] / len(stems), 3))
        for sid in ranked[:POOL]
    ]


@lru_cache(maxsize=1)
def _concept_terms():
    """Concept names and spellings in English letters, and Gurmukhi word stems, to the concepts each names.

    A word whose senses Ujjal ruled on names every concept its senses support, and
    none when he ruled it never counts (ਕਾਮਣਿ is not ਕਾਮ).
    """
    names, gurmukhi = defaultdict(set), defaultdict(set)
    vocabulary = _get_tag_vocab().get("theme_tags", {})
    for name, info in vocabulary.items():
        names[re.sub(r"\s*\(.*\)", "", name).lower().replace("-", " ")].add(name)
        for word in (info.get("gurbani_term") or "").split():
            gurmukhi[stem(unicodedata.normalize("NFC", word))].add(name)
    curated = json.loads(
        (Path(config.DATA_DIR) / "draft_vocabulary.json").read_text(encoding="utf-8")
    )
    for rule in curated.get("word_senses", []):
        word = stem(unicodedata.normalize("NFC", rule["word"]))
        gurmukhi[word] = {s["concept"] for s in rule["senses"] if s.get("concept")}
    for spelling, target in ROMAN_SPELLINGS.items():
        names[spelling] |= (
            {target} if target in vocabulary else names.get(target, set())
        )
    return {k: frozenset(v) for k, v in names.items() if v}, {
        k: frozenset(v) for k, v in gurmukhi.items()
    }


def named_concepts(query):
    """(concepts the query names, whether every word of it names one)."""
    names, gurmukhi = _concept_terms()
    found, whole = [], True
    words = roman_words(query)
    i = 0
    while i < len(words):
        pair = " ".join(words[i : i + 2])
        if i + 1 < len(words) and pair in names:
            found += sorted(names[pair])
            i += 2
            continue
        if words[i] in names:
            found += sorted(names[words[i]])
        elif words[i] not in FILLER_WORDS:
            whole = False
        i += 1
    for token in gurmukhi_stems(query):
        term = max((t for t in gurmukhi if token.startswith(t)), key=len, default=None)
        if term and gurmukhi[term]:
            found += sorted(gurmukhi[term])
        else:
            whole = False
    found = list(dict.fromkeys(found))
    return found, whole and bool(found)


def concept_shabads(concepts):
    """Shabads where the named concepts carry weight: those holding more of them first, then heavier."""
    if not concepts:
        return []
    held = {}
    for sid, group in _get_concepts().items():
        for item in group:
            if item["concept"] in concepts and (item.get("weight") or 0) > 0:
                entry = held.setdefault(sid, [0, 0.0, item["line_index"]])
                entry[0] += 1
                entry[1] += item["weight"]
    ranked = sorted(held, key=lambda s: (-held[s][0], -held[s][1], int(s)))[:POOL]
    return [(sid, held[sid][2], round(held[sid][1], 1)) for sid in ranked]


def verse_meaning(query):
    hits = []
    for match in _get_lines_vector_store().search_similar(query, n_results=VERSE_FETCH):
        meta = match.get("metadata") or {}
        title = is_title(meta.get("gurmukhi", ""), meta.get("line_index", 0))
        if title or match.get("distance") is None:
            continue
        hits.append(
            (
                str(meta.get("shabad_id")),
                meta.get("line_index"),
                round(max(0.0, 1.0 - match["distance"]), 3),
            )
        )
    return _best_per_shabad(hits)[:POOL]


def shabad_meaning(query):
    lookup, hits = _get_sggs_lookup(), []
    for match in _get_sggs_vector_store().search_similar(query, n_results=POOL):
        sid = str(match["id"])
        if match.get("distance") is None or EMPTY_SUMMARY.search(
            lookup.get(sid, {}).get("brief_meaning") or ""
        ):
            continue
        hits.append((sid, None, round(max(0.0, 1.0 - match["distance"]), 3)))
    return hits


def fuse(lists, weights):
    """(shabad, source of its verse, verse index, meaning score) by weighted reciprocal rank.

    A typed match counts in proportion to the share of the typed words its verse
    holds, so a verse holding the whole line outranks shabads that hold part of it
    and also resemble it in meaning.
    """
    score, evidence, meaning = defaultdict(float), {}, {}
    for source, ranked in lists.items():
        for rank, (sid, idx, value) in enumerate(ranked):
            share = value if source in TYPED else 1.0
            score[sid] += weights[source] * share / (RRF_K + rank)
            if source in ("verse", "shabad"):
                meaning[sid] = max(meaning.get(sid, 0.0), value)
            held = evidence.get(sid)
            if idx is not None and (
                held is None
                or EVIDENCE_ORDER.index(source) < EVIDENCE_ORDER.index(held[0])
            ):
                evidence[sid] = (source, idx)
    order = sorted(score, key=lambda s: (-score[s], int(s)))
    return [
        (sid, *evidence.get(sid, ("shabad", None)), meaning.get(sid)) for sid in order
    ]


@lru_cache(maxsize=256)
def candidates(query):
    """Fused local results for a normalized query, best first.

    The embedding model reads English only. When a typed line finds its verse,
    that verse's translation is searched by meaning instead, so the rest of the
    list holds related verses rather than whatever matches Punjabi letters.
    """
    concepts, whole = named_concepts(query)
    lists = {"concept": concept_shabads(concepts)}
    if GURMUKHI.search(query):
        lists["words"] = typed = gurmukhi_words(query)
        meaning = _found_translation(typed) if len(gurmukhi_stems(query)) > 1 else None
    else:
        lists["line"] = typed = roman_lines(query)
        meaning = _found_translation(typed) or query
    if meaning:
        lists["verse"] = verse_meaning(meaning)
        lists["shabad"] = shabad_meaning(meaning)
    weights = {
        **WEIGHTS,
        "concept": NAMED_CONCEPT_WEIGHT if whole else WEIGHTS["concept"],
    }
    return tuple(fuse({k: v for k, v in lists.items() if v}, weights)[:POOL])


def _verse(sid, idx):
    verses = (corpus.shabad(sid) or {}).get("verses", [])
    return verses[idx] if idx is not None and 0 <= idx < len(verses) else None


def _found_translation(typed):
    """English of the verse a typed line found, when the verse holds most of the line."""
    if not typed or typed[0][2] < FOUND_LINE:
        return None
    verse = _verse(typed[0][0], typed[0][1])
    return verse["english"] if verse and verse["english"] else None


def _result(sid, source, idx, meaning, reason=None):
    meta, lookup = (
        _get_graph()["metadata"].get(sid, {}),
        _get_sggs_lookup().get(sid, {}),
    )
    info, verse = corpus.shabad(sid) or {}, _verse(sid, idx)
    return {
        "banidb_shabad_id": sid,
        "title_gurmukhi": verse["gurmukhi"] if verse else meta.get("gurmukhi", ""),
        "title_transliteration": meta.get("title", ""),
        "first_line_translation": verse["english"]
        if verse
        else lookup.get("brief_meaning", ""),
        "matched_line_index": verse["index"] if verse else None,
        "match": source,
        "badge": BADGES[source],
        "ang_number": info.get("ang") or meta.get("ang", 0),
        "raag": info.get("raag") or meta.get("raag", ""),
        "writer": info.get("writer", ""),
        "score": meaning,
        "reason": reason,
    }


def rerank_enabled():
    return os.getenv("SHABADVERSE_RERANK") == "1" and bool(
        os.getenv("ANTHROPIC_API_KEY")
    )


def cached_order(query):
    with _limits:
        order = _orders.get(query.lower())
        if order is not None:
            _orders.move_to_end(query.lower())
        return order


def _reserve(visitor):
    """Count one reordering against the daily cap and the visitor's window, or refuse."""
    now = time.time()
    with _limits:
        while _calls and now - _calls[0] > DAY:
            _calls.popleft()
        if len(_visitors) > VISITORS_TRACKED:
            idle = [
                v
                for v, times in _visitors.items()
                if not times or now - times[-1] > VISITOR_WINDOW
            ]
            for v in idle:
                del _visitors[v]
        recent = _visitors[visitor]
        while recent and now - recent[0] > VISITOR_WINDOW:
            recent.popleft()
        if not recent:
            del _visitors[visitor]
        if len(_calls) >= RERANK_DAILY_CAP or len(recent) >= VISITOR_LIMIT:
            return False
        _calls.append(now)
        _visitors[visitor].append(now)
        return True


def _candidate_line(sid, idx):
    verse, lookup = _verse(sid, idx), _get_sggs_lookup().get(sid, {})
    entry = {"id": sid}
    if verse:
        entry.update(
            verse=verse["english"], transliteration=verse["transliteration"][:160]
        )
    else:
        entry["summary"] = (lookup.get("brief_meaning") or "")[:300]
    rahao = (lookup.get("rahao_english") or "")[:300]
    if rahao and rahao != entry.get("verse"):
        entry["rahao"] = rahao
    return json.dumps(entry, ensure_ascii=False)


def rerank(query, pool, visitor):
    """Claude Haiku 5.5's order for the pool as (shabad, reason) pairs, or None to keep the local order."""
    if not pool or not rerank_enabled() or not _reserve(visitor):
        return None
    import anthropic

    candidates_text = "\n".join(_candidate_line(sid, idx) for sid, _, idx, _ in pool)
    try:
        response = anthropic.Anthropic(
            timeout=RERANK_TIMEOUT, max_retries=1
        ).messages.create(
            model=RERANK_MODEL,
            max_tokens=1024,
            thinking={"type": "disabled"},
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": RERANK_SCHEMA},
            },
            system=RERANK_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"Search: {query}\n\nCandidates, one per line:\n{candidates_text}",
                }
            ],
        )
    except anthropic.APIError as error:
        log.warning("Reordering failed: %s", error)
        return None
    if response.stop_reason != "end_turn":
        log.warning("Reordering stopped early: %s", response.stop_reason)
        return None
    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        picks = json.loads(text).get("results", [])
    except (json.JSONDecodeError, AttributeError) as error:
        log.warning("Reordering returned unreadable output: %s", error)
        return None
    allowed, order = {sid for sid, *_ in pool}, []
    for pick in picks:
        sid = str(pick.get("id", ""))
        if sid in allowed and sid not in {s for s, _ in order}:
            order.append((sid, str(pick.get("reason", ""))[:REASON_CHARS]))
    order = order[:RERANK_KEEP]
    if not order:
        return None
    with _limits:
        _orders[query.lower()] = order
        while len(_orders) > ORDER_CACHE:
            _orders.popitem(last=False)
    return order


def _visitor():
    # Caddy sets the client address last; anything earlier came from the client.
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (
        forwarded.split(",")[-1].strip()
        if forwarded
        else (request.remote_addr or "unknown")
    )


@graph_bp.route("/graph/semantic-search")
def graph_semantic_search():
    """Search by meaning, a remembered line, Gurmukhi words or a concept name.

    Query params:
        q (str): the search, at least 3 characters
        limit (int): max results (default 10, capped at 25)
        rerank (1): ask Claude Haiku 5.5 to order the results when the server allows it
    """
    q = normalize_query(request.args.get("q", ""))
    limit = max(1, min(request.args.get("limit", 10, type=int), MAX_RESULTS))
    if len(q) < 3:
        return jsonify({"results": [], "reordered": False, "rerank_available": False})
    pool = candidates(q)
    by_id = {sid: (source, idx, meaning) for sid, source, idx, meaning in pool}
    order = cached_order(q)
    if order is None and request.args.get("rerank") == "1":
        order = rerank(q, pool, _visitor())
    if order:
        results = [
            _result(sid, *by_id[sid], reason=reason)
            for sid, reason in order
            if sid in by_id
        ]
        return jsonify(
            {"results": results[:limit], "reordered": True, "rerank_available": False}
        )
    results = [
        _result(sid, source, idx, meaning) for sid, source, idx, meaning in pool[:limit]
    ]
    return jsonify(
        {"results": results, "reordered": False, "rerank_available": rerank_enabled()}
    )
