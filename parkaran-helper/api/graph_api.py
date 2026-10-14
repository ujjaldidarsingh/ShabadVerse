"""Graph API endpoints for the interactive explorer."""

import json
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from flask import Blueprint, jsonify, request

import config
from database import corpus

graph_bp = Blueprint("graph", __name__)

# Module-level cache
_graph_data = None
_tag_vocab = None
_sggs_lookup = None
_sggs_vector_store = None
_lines_vector_store = None

# A tag carried by more than this share of the corpus is structural, not
# distinctive: labelling a cluster "Naam Simran" when a third of Gurbani carries
# that tag tells the reader nothing about why THESE shabads sit together. Such
# tags stay on shabads and stay searchable; they just never title a cluster.
CLUSTER_LABEL_MAX_COVERAGE = 0.25


def _pick_cluster_tag(candidates, tag_index, n_shabads):
    """Choose the most informative tag to title a cluster.

    Prefers the rarest candidate that is below the coverage cap. If every
    candidate is structural (e.g. a shabad tagged only with broad themes), falls
    back to the rarest of them rather than dropping the cluster.
    """
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda t: (len(tag_index.get(t, [])), t))
    cap = CLUSTER_LABEL_MAX_COVERAGE * max(1, n_shabads)
    for tag in ranked:
        if len(tag_index.get(tag, [])) <= cap:
            return tag
    return ranked[0]


def _get_sggs_vector_store():
    """Lazy-load SGGS ChromaDB vector store for meaning search."""
    from database.vector_store import ShabadVectorStore
    global _sggs_vector_store
    if _sggs_vector_store is None:
        _sggs_vector_store = ShabadVectorStore(collection_name=config.SGGS_COLLECTION_NAME)
    return _sggs_vector_store


def _get_lines_vector_store():
    """Lazy-load the per-verse (tuk) ChromaDB collection used by line matching."""
    from database.vector_store import ShabadVectorStore
    global _lines_vector_store
    if _lines_vector_store is None:
        _lines_vector_store = ShabadVectorStore(collection_name=config.SGGS_LINES_COLLECTION_NAME)
    return _lines_vector_store


# ---- Line matching -----------------------------------------------------------
#
# Two separate algorithms answer two different questions:
#
#   match=shabad  "Which shabads are ABOUT the same things as this one?"
#                 Precomputed whole-shabad graph: concept overlap plus shabad
#                 vectors. Clusters are titled by concepts.
#
#   match=line    "Where else does THIS thought appear?"
#                 Live search over the saved BaniDB English translation of every
#                 verse. The score is translation similarity alone. Concepts are
#                 whole-shabad judgments; mixing them in as a prior pulled weaker
#                 verse matches above stronger ones.

# Over-fetch lines so that after collapsing to one line per shabad we still have
# a full neighbor set. Long shabads would otherwise crowd out whole shabads.
LINE_FETCH_MULTIPLIER = 12

# A line match can be grouped under a word both verses share, when the word is
# distinctive: at least three letters, in at most SHARED_WORD_MAX_SHARE of all
# verses, and not a pronoun, particle or heading word. A word groups matches only
# when at least SHARED_WORD_MIN_GROUP of them share it; the rest sit under
# SIMILAR_TRANSLATION. Stems drop one final vowel sign or nasal mark, so ਠਾਕੁਰੁ and
# ਠਾਕੁਰ count as one word.
SHARED_WORD_MAX_SHARE = 0.01
SHARED_WORD_MIN_LETTERS = 3
SHARED_WORD_MIN_GROUP = 2
SHARED_WORD_STOPLIST = frozenset({
    "ਸਲੋਕ", "ਪਉੜ", "ਕਬੀਰ", "ਫਰੀਦ", "ਅਵਰ", "ਆਪਣ", "ਅਪਣ", "ਅਪਨ", "ਅਪੁਨ", "ਹਮਾਰ", "ਹਮਰ", "ਤੁਮਾਰ",
    "ਤੁਮਰ", "ਕਵਨ", "ਕਬਹ", "ਸਭਨ", "ਊਪਰ", "ਆਇਆ", "ਗਇਆ", "ਭਇਆ", "ਰਹਿਆ", "ਮਿਲਿਆ",
    "ਪਾਵਹ", "ਗਾਵਹ", "ਬਹੁਤ", "ਅਨਿਕ", "ਵਿਚਹ", "ਬਾਹਰ", "ਅੰਦਰ",
})
SIMILAR_TRANSLATION = "Similar translation"
_PUNCTUATION = re.compile(r"[॥।0-9੦-੯]")
_FINAL_NASAL = re.compile("[\u0A02\u0A70]$")
_FINAL_VOWEL = re.compile("[\u0A3E-\u0A4C]$")
_LETTER = re.compile("[\u0A05-\u0A39\u0A59-\u0A5E\u0A72-\u0A74]")
_word_frequency = None


def _verse_words(text):
    """(word as written, stem) for each distinctive-length word in a verse."""
    words = []
    for token in _PUNCTUATION.sub(" ", unicodedata.normalize("NFC", text or "")).split():
        stem = _FINAL_VOWEL.sub("", _FINAL_NASAL.sub("", token))
        if len(_LETTER.findall(stem)) >= SHARED_WORD_MIN_LETTERS and stem not in SHARED_WORD_STOPLIST:
            words.append((token, stem))
    return words


def _get_word_frequency():
    """How many verses of the corpus contain each stem, and how many verses there are."""
    global _word_frequency
    if _word_frequency is None:
        counts, verses = Counter(), 0
        for record in _get_sggs_lookup().values():
            for verse in (record.get("gurmukhi_text") or "").split("\n"):
                if verse.strip():
                    verses += 1
                    counts.update({stem for _, stem in _verse_words(verse)})
        _word_frequency = (counts, verses)
    return _word_frequency


def _shared_word(anchor_gurmukhi, matched_gurmukhi):
    """The rarest distinctive word both verses contain, as written in the anchor."""
    counts, verses = _get_word_frequency()
    limit = SHARED_WORD_MAX_SHARE * max(1, verses)
    matched = {stem for _, stem in _verse_words(matched_gurmukhi)}
    shared = [(counts.get(stem, 0), token) for token, stem in _verse_words(anchor_gurmukhi)
              if stem in matched and counts.get(stem, 0) <= limit]
    return min(shared)[1] if shared else None


def _resolve_anchor_line(shabad_id, line_index):
    """Pick the line whose meaning drives a line-mode expansion.

    Explicit choice wins. Otherwise the rahao: it is the shabad's own statement
    of what it is about, so it is the most faithful default anchor. Failing that
    (saloks carry no rahao), the first verse that is not a heading. Raag headings
    with four or more translated words are in the index, so they are skipped here.

    Returns (line_index, english, gurmukhi) or None when the shabad has no
    embeddable lines at all.
    """
    store = _get_lines_vector_store()
    got = store.collection.get(where={"shabad_id": str(shabad_id)})
    metas = got.get("metadatas") or []
    if not metas:
        return None

    if line_index is not None:
        chosen = next((m for m in metas if m["line_index"] == line_index), None)
        if chosen is None:
            return None
    else:
        verses = [m for m in metas if not corpus.is_heading(m.get("gurmukhi", ""))] or metas
        rahao = ([m for m in verses if corpus.RAHAO_MARK.search(m.get("gurmukhi", ""))]
                 or [m for m in verses if m.get("is_rahao")])
        chosen = min(rahao or verses, key=lambda m: m["line_index"])

    return chosen["line_index"], chosen["english"], chosen.get("gurmukhi", "")


def _line_neighbors(shabad_id, line_index, limit, threshold):
    """Find shabads containing a verse whose translation is closest to the anchor's.

    Returns (results, anchor): one result per shabad carrying its best-matching
    verse, and the anchor verse the search started from.
    """
    anchor = _resolve_anchor_line(shabad_id, line_index)
    if not anchor:
        return [], None
    anchor_idx, anchor_english, anchor_gurmukhi = anchor

    store = _get_lines_vector_store()
    if store.get_count() == 0:
        return [], None

    # Matches arrive best first, so the first verse seen for a shabad is its best.
    results, seen_text = {}, set()
    for match in store.search_similar(anchor_english, n_results=limit * LINE_FETCH_MULTIPLIER):
        meta = match.get("metadata") or {}
        cid = str(meta.get("shabad_id", ""))
        gurmukhi = meta.get("gurmukhi", "")
        if not cid or cid == str(shabad_id) or cid in results or corpus.is_heading(gurmukhi):
            continue
        english = (meta.get("english") or "").strip()
        # Refrains repeat verbatim across shabads; one instance is informative,
        # ten are noise.
        if english.lower() in seen_text:
            continue
        seen_text.add(english.lower())
        distance = match.get("distance")
        similarity = round(max(0.0, 1.0 - distance), 3) if distance is not None else 0.0
        results[cid] = {
            "id": cid,
            "score": similarity,
            "line_score": similarity,
            "matched_line_index": meta.get("line_index"),
            "matched_line_gurmukhi": gurmukhi,
            "matched_line_english": english,
            "matched_line_is_rahao": bool(meta.get("is_rahao")),
            "shared_word": _shared_word(anchor_gurmukhi, gurmukhi),
        }

    ranked = sorted((r for r in results.values() if r["score"] >= threshold), key=lambda r: (-r["score"], r["id"]))
    return ranked[:limit], {
        "line_index": anchor_idx,
        "english": anchor_english,
        "gurmukhi": anchor_gurmukhi,
    }


def _get_graph():
    global _graph_data
    if _graph_data is None:
        path = os.path.join(config.DATA_DIR, "similarity_graph.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _graph_data = json.load(f)
        else:
            raise RuntimeError("Missing graph dataset")
    return _graph_data


def _get_tag_vocab():
    global _tag_vocab
    if _tag_vocab is None:
        path = os.path.join(config.DATA_DIR, "tag_vocabulary.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _tag_vocab = json.load(f)
        else:
            raise RuntimeError("Missing concept vocabulary")
    return _tag_vocab


def _get_sggs_lookup():
    """Lazy-load SGGS shabads for full text data (used by neighbor endpoint)."""
    global _sggs_lookup
    if _sggs_lookup is None:
        if os.path.exists(config.SGGS_DATA_PATH):
            with open(config.SGGS_DATA_PATH, encoding="utf-8") as f:
                sggs_list = json.load(f)
            _sggs_lookup = {str(s["banidb_shabad_id"]): s for s in sggs_list}
        else:
            raise RuntimeError("Missing scripture dataset")
    return _sggs_lookup


@graph_bp.route("/graph/init")
def graph_init():
    """Return metadata + tag_index + tag_vocab for client-side graph rendering."""
    graph = _get_graph()
    vocab = _get_tag_vocab()

    # Build compact tag vocab (description + gurbani_term only)
    tag_vocab = {}
    for tag_name, tag_data in vocab.get("theme_tags", {}).items():
        tag_vocab[tag_name] = {
            "description": tag_data.get("description", ""),
            "gurbani_term": tag_data.get("gurbani_term", ""),
            "confidence": tag_data.get("confidence", ""),
        }
    for tag_name, tag_data in vocab.get("mood_tags", {}).items():
        tag_vocab[tag_name] = {
            "description": tag_data.get("description", ""),
            "gurbani_term": tag_data.get("gurbani_term", ""),
            "confidence": tag_data.get("confidence", ""),
        }

    return jsonify({
        "metadata": {sid: {k: m.get(k) for k in ("title", "gurmukhi", "raag", "ang", "tags")}
                     for sid, m in graph.get("metadata", {}).items()},
        "tag_index": graph.get("tag_index", {}),
        "tag_vocab": tag_vocab,
        "stats": graph.get("stats", {}),
    })


def _enrich(nid, score, metadata, sggs_lookup):
    """Display fields for one neighbor, from graph metadata with corpus fallbacks."""
    n_meta = metadata.get(nid, {})
    n_sggs = sggs_lookup.get(nid, {})
    return {
        "id": nid,
        "score": score,
        "title": n_meta.get("title") or n_sggs.get("display_name") or (n_sggs.get("transliteration") or "")[:80],
        "gurmukhi": n_meta.get("gurmukhi") or n_sggs.get("display_gurmukhi") or "",
        "raag": n_meta.get("raag", ""),
        "writer": n_meta.get("writer", ""),
        "ang": n_meta.get("ang", 0),
        "tags": n_meta.get("tags", []),
        "is_repertoire": False,
        "primary_theme": n_meta.get("primary_theme", ""),
        "mood": n_meta.get("mood", ""),
        "brief_meaning": n_meta.get("brief_meaning") or n_sggs.get("brief_meaning") or "",
    }


def _group_graph_neighbors(raw_neighbors, threshold, my_tags, metadata, sggs_lookup, tag_index, max_neighbors, per_tag_cap):
    """Whole-shabad mode: cluster precomputed neighbors under concept labels."""
    my_tags_set = set(my_tags)
    by_tag = defaultdict(list)
    seen_globally = set()
    n_shabads = len(metadata) or 1
    for n in raw_neighbors:
        nid = str(n["id"])
        if n["score"] < threshold or nid in seen_globally:
            continue
        seen_globally.add(nid)
        enriched = _enrich(nid, n["score"], metadata, sggs_lookup)

        shared = set(n.get("shared_tags", []))
        n_all_tags = set(enriched["tags"])
        new_tags = n_all_tags - my_tags_set

        if shared == my_tags_set or not new_tags:
            # Same thematic direction. Title the cluster with the most
            # distinctive shared tag: one cluster, not one per shared tag,
            # which previously scattered a single neighbor across every
            # broad theme it happened to carry.
            label = _pick_cluster_tag(list(shared), tag_index, n_shabads)
        else:
            label = _pick_cluster_tag(list(new_tags), tag_index, n_shabads)
        if not label:
            label = _pick_cluster_tag(list(n_all_tags), tag_index, n_shabads) or "Translation similarity"
        by_tag[label].append(enriched)

    # Bound the expanded view globally, preserving unmodified similarity.
    if sum(map(len, by_tag.values())) > max_neighbors:
        chosen = sorted((n for group in by_tag.values() for n in group), key=lambda n: (-n["score"], n["id"]))[:max_neighbors]
        keep = {n["id"] for n in chosen}
        by_tag = {tag: [n for n in group if n["id"] in keep] for tag, group in by_tag.items()}
    for group in by_tag.values():
        for n in group:
            n["rank_score"] = round(n["score"], 3)
    for tag in by_tag:
        by_tag[tag].sort(key=lambda x: (-x["rank_score"], x["id"]))
        by_tag[tag] = by_tag[tag][:per_tag_cap]

    # Keep small clusters truthful. A visual grouping must not invent a concept.
    by_tag = {tag: items for tag, items in by_tag.items() if items}
    kinds = {tag: "concept" if tag in tag_index else "untagged" for tag in by_tag}
    return by_tag, kinds


def _group_line_hits(hits, metadata, sggs_lookup):
    """Line mode: group matches by a distinctive word they share with the anchor.

    No concept labels: the reason for a line match is the matched verse itself.
    """
    word_counts = Counter(h["shared_word"] for h in hits if h["shared_word"])
    by_tag = defaultdict(list)
    for hit in hits:
        enriched = _enrich(hit["id"], hit["score"], metadata, sggs_lookup)
        enriched.update({key: hit[key] for key in (
            "matched_line_index", "matched_line_gurmukhi", "matched_line_english",
            "matched_line_is_rahao", "line_score", "shared_word")})
        enriched["rank_score"] = hit["score"]
        word = hit["shared_word"]
        label = word if word and word_counts[word] >= SHARED_WORD_MIN_GROUP else SIMILAR_TRANSLATION
        by_tag[label].append(enriched)
    kinds = {tag: "similar_translation" if tag == SIMILAR_TRANSLATION else "shared_word" for tag in by_tag}
    return dict(by_tag), kinds


@graph_bp.route("/graph/neighbors/<shabad_id>")
def graph_neighbors(shabad_id):
    """Return neighbors for a shabad, grouped for display.

    Query params:
        threshold (float): Min score to include (default 0.3). Each mode has its
            own score: a ranking heuristic for whole shabads, verse translation
            similarity for lines.
        per_tag (int): Max neighbors per concept cluster in whole-shabad mode (default 8)
        max_neighbors (int): Max neighbors overall (default 30, capped at 60)
        match (str): "shabad" (default) or "line". See the Line matching section
            above: these are two different algorithms, not one with a filter.
        line_index (int): in match=line, anchor on this verse. Defaults to the
            shabad's rahao, then its first verse that is not a heading.
    """
    graph = _get_graph()
    sggs_lookup = _get_sggs_lookup()
    metadata = graph.get("metadata", {})

    threshold = request.args.get("threshold", 0.3, type=float)
    if not math.isfinite(threshold):
        return jsonify({"error": "Invalid threshold"}), 400
    threshold = max(0.0, min(threshold, 1.0))
    per_tag_cap = max(1, min(request.args.get("per_tag", 8, type=int), 30))
    max_neighbors = max(1, min(request.args.get("max_neighbors", 30, type=int), 60))
    match_mode = request.args.get("match", "shabad", type=str).lower()
    if match_mode not in ("shabad", "line"):
        match_mode = "shabad"
    line_index = request.args.get("line_index", type=int)
    if str(shabad_id) not in metadata:
        return jsonify({"error": "Shabad not found"}), 404
    requested_match = match_mode
    fallback_reason = None
    my_tags = metadata.get(str(shabad_id), {}).get("tags", [])
    tag_index = graph.get("tag_index", {})

    line_anchor = None
    if match_mode == "line":
        hits, line_anchor = _line_neighbors(shabad_id, line_index, max_neighbors, threshold)
        if hits:
            by_tag, label_kinds = _group_line_hits(hits, metadata, sggs_lookup)
            scores = [h["score"] for h in hits]
        else:
            # A handful of shabads carry no embeddable lines (headers only), and
            # a strict threshold can filter everything out. Never hand back an
            # empty expansion: fall back to the shabad-level graph.
            match_mode = "shabad"
            fallback_reason = "No matching indexed lines at this threshold; showing whole-shabad connections."
            line_anchor = None
    if match_mode == "shabad":
        raw_neighbors = graph.get("neighbors", {}).get(str(shabad_id), [])
        by_tag, label_kinds = _group_graph_neighbors(
            raw_neighbors, threshold, my_tags, metadata, sggs_lookup, tag_index, max_neighbors, per_tag_cap)
        scores = [n["score"] for n in raw_neighbors]

    total_available = len(scores)
    scores = scores or [0]
    return jsonify({
        "id": shabad_id,
        "tags": my_tags,
        "by_tag": by_tag,
        "label_kinds": label_kinds,
        "total_available": total_available,
        "total_shown": sum(len(v) for v in by_tag.values()),
        "score_range": {
            "min": round(min(scores), 3),
            "max": round(max(scores), 3),
            "median": round(sorted(scores)[len(scores) // 2], 3),
        },
        "threshold_used": threshold,
        "match": match_mode,
        "requested_match": requested_match,
        "fallback_reason": fallback_reason,
        "score_kind": ("verse translation similarity, not interpretive confidence" if match_mode == "line"
                       else "ranking heuristic, not interpretive confidence"),
        # In line mode, the verse the expansion was anchored on. The frontend can
        # show "matching on this line" and offer to re-anchor elsewhere.
        "anchor_line": line_anchor,
    })


@graph_bp.route("/graph/shabads", methods=["POST"])
def get_shabads_by_ids():
    """Return full shabad data for an array of BaniDB IDs.

    Used by the reviewer to load complete shabad details (Gurmukhi text,
    translation, tags, themes) without depending on the personal library.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("ids"), list) or len(data["ids"]) > 200:
        return jsonify({"error": "Supply an ids array of at most 200 shabads"}), 400
    ids = [str(i) for i in data["ids"]]
    if any(sid not in _get_graph().get("metadata", {}) for sid in ids):
        return jsonify({"error": "Unknown shabad ID"}), 404

    graph = _get_graph()
    sggs_lookup = _get_sggs_lookup()
    metadata = graph.get("metadata", {})
    neighbors_map = graph.get("neighbors", {})

    results = []
    for idx, sid in enumerate(ids):
        meta = metadata.get(sid, {})
        sggs = sggs_lookup.get(sid, {})
        source = corpus.shabad(sid) or {}

        # Compute shared tags with next shabad in the list (for transition display)
        shared_with_next = []
        if idx < len(ids) - 1:
            next_sid = ids[idx + 1]
            my_tags = set(meta.get("tags", []))
            next_meta = metadata.get(next_sid, {})
            next_tags = set(next_meta.get("tags", []))
            shared_with_next = sorted(my_tags & next_tags)

        results.append({
            "id": sid,
            "title": meta.get("title") or sggs.get("display_name") or (sggs.get("transliteration") or "")[:80],
            "gurmukhi": meta.get("gurmukhi") or sggs.get("display_gurmukhi") or "",
            "gurmukhi_text": sggs.get("gurmukhi_text") or "",
            "verses": source.get("verses", []),
            "concept_evidence": _concept_evidence(sid),
            "interpretation_notice": "Themes and summaries are machine-assisted interpretation; read the full shabad.",
            "english_translation": sggs.get("english_translation") or "",
            "transliteration": sggs.get("transliteration") or "",
            "brief_meaning": sggs.get("brief_meaning") or "",
            "rahao_gurmukhi": sggs.get("rahao_gurmukhi") or "",
            "rahao_english": sggs.get("rahao_english") or "",
            "raag": meta.get("raag") or sggs.get("sggs_raag") or "",
            "writer": source.get("writer") or meta.get("writer") or sggs.get("writer") or "",
            "ang": meta.get("ang") or sggs.get("ang_number") or 0,
            "tags": meta.get("tags", []),
            "primary_theme": meta.get("primary_theme") or sggs.get("primary_theme") or "",
            "mood": meta.get("mood") or sggs.get("mood") or "",
            "is_repertoire": False,
            "shared_tags_with_next": shared_with_next,
        })

    return jsonify({"shabads": results})


@graph_bp.route("/graph/shabad/<shabad_id>/verses")
def get_shabad_verses_graph(shabad_id):
    """Return verse-level data for a shabad (via BaniDB cache)."""
    data = corpus.shabad(shabad_id)
    if data is None:
        return jsonify({"error": "Shabad not found"}), 404
    data["concepts"] = _concept_evidence(str(shabad_id))
    return jsonify(data)


@graph_bp.route("/graph/search")
def graph_search():
    """Search first letters entirely within the local scripture snapshot."""
    q = request.args.get("q", "").strip()[:200]
    searchtype = request.args.get("searchtype", 0, type=int)
    if searchtype not in (0, 1):
        return jsonify({"error": "Use searchtype 0 (start) or 1 (anywhere)"}), 400
    return jsonify(corpus.search(q, searchtype))


@graph_bp.route("/tags")
def list_tags():
    """Return all tags with counts and descriptions."""
    graph = _get_graph()
    vocab = _get_tag_vocab()
    tag_index = graph.get("tag_index", {})

    tags = []
    for tag_name, shabad_ids in tag_index.items():
        tag_data = vocab.get("theme_tags", {}).get(tag_name) or vocab.get("mood_tags", {}).get(tag_name, {})
        tags.append({
            "tag": tag_name,
            "count": len(shabad_ids),
            "description": tag_data.get("description", ""),
            "gurbani_term": tag_data.get("gurbani_term", ""),
            "confidence": tag_data.get("confidence", ""),
        })

    tags.sort(key=lambda t: t["count"], reverse=True)
    return jsonify(tags)


@graph_bp.route("/tags/<tag>/shabads")
def tag_shabads(tag):
    """Return shabads for a given tag with metadata."""
    graph = _get_graph()
    metadata = graph.get("metadata", {})
    tag_index = graph.get("tag_index", {})

    shabad_ids = tag_index.get(tag, [])
    if not shabad_ids:
        return jsonify({"tag": tag, "shabads": [], "total": 0})

    limit = max(1, min(request.args.get("limit", 50, type=int), 100))
    offset = max(0, request.args.get("offset", 0, type=int))

    page = shabad_ids[offset : offset + limit]
    shabads = []
    for sid in page:
        meta = metadata.get(str(sid), {})
        shabads.append({
            "id": str(sid),
            "title": meta.get("title", ""),
            "raag": meta.get("raag", ""),
            "writer": meta.get("writer", ""),
            "ang": meta.get("ang", 0),
            "tags": meta.get("tags", []),
            "primary_theme": meta.get("primary_theme", ""),
            "mood": meta.get("mood", ""),
        })

    return jsonify({
        "tag": tag,
        "shabads": shabads,
        "total": len(shabad_ids),
        "offset": offset,
        "limit": limit,
    })


_concepts = None


def _get_concepts():
    global _concepts
    if _concepts is None:
        path = os.path.join(config.DATA_DIR, "concept_tags.json")
        with open(path, encoding="utf-8") as handle:
            _concepts = json.load(handle)
    return _concepts


@graph_bp.route("/graph/shabad/<shabad_id>/evidence")
def shabad_evidence(shabad_id):
    if shabad_id not in _get_sggs_lookup():
        return jsonify({"error": "Shabad not found"}), 404
    record = _get_sggs_lookup()[shabad_id]
    source = corpus.shabad(shabad_id) or {}
    vocab = _get_tag_vocab().get("theme_tags", {})
    assignments = [{**item, "confidence": vocab.get(item["concept"], {}).get("confidence", "")}
                   for item in _get_concepts().get(shabad_id, [])]
    return jsonify({"id": shabad_id, "concepts": assignments,
                    "brief_meaning": record.get("brief_meaning", ""),
                    "writer": source.get("writer", ""),
                    "notice": "Lexical means a word was found; inferred means translation similarity. Neither is a ruling on the shabad."})


def _concept_evidence(shabad_id):
    vocab = _get_tag_vocab().get("theme_tags", {})
    return [{**item, "confidence": vocab.get(item["concept"], {}).get("confidence", "")}
            for item in _get_concepts().get(shabad_id, [])]
