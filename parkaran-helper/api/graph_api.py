"""Graph API endpoints for the interactive explorer."""

import json
import os
from collections import defaultdict
from flask import Blueprint, jsonify, request

import config
from database.vector_store import ShabadVectorStore

graph_bp = Blueprint("graph", __name__)

# Module-level cache
_graph_data = None
_tag_vocab = None
_sggs_lookup = None
_sggs_vector_store = None


def _get_sggs_vector_store():
    """Lazy-load SGGS ChromaDB vector store for tuk-aware search."""
    global _sggs_vector_store
    if _sggs_vector_store is None:
        _sggs_vector_store = ShabadVectorStore(collection_name=config.SGGS_COLLECTION_NAME)
    return _sggs_vector_store


def _get_graph():
    global _graph_data
    if _graph_data is None:
        path = os.path.join(config.DATA_DIR, "similarity_graph.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _graph_data = json.load(f)
        else:
            _graph_data = {"neighbors": {}, "tag_index": {}, "metadata": {}, "stats": {}}
    return _graph_data


def _get_tag_vocab():
    global _tag_vocab
    if _tag_vocab is None:
        path = os.path.join(config.DATA_DIR, "tag_vocabulary.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _tag_vocab = json.load(f)
        else:
            _tag_vocab = {"theme_tags": {}, "mood_tags": {}}
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
            _sggs_lookup = {}
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
        }
    for tag_name, tag_data in vocab.get("mood_tags", {}).items():
        tag_vocab[tag_name] = {
            "description": tag_data.get("description", ""),
            "gurbani_term": tag_data.get("gurbani_term", ""),
        }

    return jsonify({
        "metadata": graph.get("metadata", {}),
        "tag_index": graph.get("tag_index", {}),
        "tag_vocab": tag_vocab,
        "stats": graph.get("stats", {}),
    })


@graph_bp.route("/graph/neighbors/<shabad_id>")
def graph_neighbors(shabad_id):
    """Return neighbors for a shabad, grouped by shared tag.

    Query params:
        threshold (float): Min score to include (default 0.3)
        per_tag (int): Max neighbors per tag cluster (default 8)
    """
    graph = _get_graph()
    sggs_lookup = _get_sggs_lookup()
    metadata = graph.get("metadata", {})

    threshold = request.args.get("threshold", 0.3, type=float)
    per_tag_cap = request.args.get("per_tag", 8, type=int)
    tuk_english = request.args.get("tuk_english", "", type=str).strip()

    # Get this shabad's tags from graph metadata
    my_meta = metadata.get(str(shabad_id), {})
    my_tags = my_meta.get("tags", [])

    # ── BLENDED PATH: tuk vector search + graph neighbors for tag diversity ──
    # When tuk_english is provided, vector search finds semantically close shabads
    # to the specific verse. Graph neighbors fill in tag-based diversity.
    # When no tuk, pure graph path (pre-computed, instant).
    tuk_results = {}  # nid -> enriched dict (from vector search)
    if tuk_english:
        store = _get_sggs_vector_store()
        if store.get_count() > 0:
            results = store.search_similar(
                tuk_english, n_results=30, exclude_ids={str(shabad_id)}
            )
            for r in results:
                nid = str(r["id"])
                n_meta = metadata.get(nid, {})
                n_sggs = sggs_lookup.get(nid, {})
                score = max(0, min(1, 1 - (r.get("distance") or 0.5)))
                if score < threshold:
                    continue
                tuk_results[nid] = {
                    "id": nid,
                    "score": round(score, 3),
                    "title": n_meta.get("title") or n_sggs.get("display_name") or (n_sggs.get("transliteration") or "")[:80],
                    "gurmukhi": n_meta.get("gurmukhi") or n_sggs.get("display_gurmukhi") or "",
                    "raag": n_meta.get("raag") or r["metadata"].get("sggs_raag", ""),
                    "writer": n_meta.get("writer") or r["metadata"].get("writer", ""),
                    "ang": n_meta.get("ang") or r["metadata"].get("ang", 0),
                    "tags": n_meta.get("tags", []),
                    "is_repertoire": n_meta.get("is_repertoire", False),
                    "primary_theme": n_meta.get("primary_theme") or r["metadata"].get("primary_theme", ""),
                    "mood": n_meta.get("mood") or r["metadata"].get("mood", ""),
                    "brief_meaning": n_meta.get("brief_meaning") or n_sggs.get("brief_meaning") or r["metadata"].get("brief_meaning", ""),
                }

    # ── GRAPH PATH: pre-computed neighbors ──
    raw_neighbors = graph.get("neighbors", {}).get(str(shabad_id), [])
    neighbors = [n for n in raw_neighbors if n["score"] >= threshold]

    # Group neighbors by thematic direction
    my_tags_set = set(my_tags)
    by_tag = defaultdict(list)
    seen_globally = set()

    # First: add tuk vector results (semantically closest to searched verse)
    for nid, enriched in tuk_results.items():
        seen_globally.add(nid)
        tags = enriched.get("tags", [])
        if not tags:
            tags = [enriched.get("primary_theme") or "Similar"]
        # Place under most relevant tag
        matching_tags = [t for t in tags if t in my_tags_set]
        if matching_tags:
            by_tag[matching_tags[0]].append(enriched)
        else:
            # Branching: use the neighbor's most specific tag
            n_all_tags = set(tags)
            new_tags = n_all_tags - my_tags_set
            if new_tags:
                best_new = min(new_tags, key=lambda t: len(graph.get("tag_index", {}).get(t, [])))
                by_tag[best_new].append(enriched)
            elif tags:
                by_tag[tags[0]].append(enriched)

    # Then: add graph neighbors for tag diversity (skip those already from tuk search)
    for n in neighbors:
        nid = str(n["id"])
        if nid in seen_globally:
            continue
        seen_globally.add(nid)

        n_meta = metadata.get(nid, {})
        n_sggs = sggs_lookup.get(nid, {})

        enriched = {
            "id": nid,
            "score": n["score"],
            "title": n_meta.get("title") or n_sggs.get("display_name") or (n_sggs.get("transliteration") or "")[:80],
            "gurmukhi": n_meta.get("gurmukhi") or n_sggs.get("display_gurmukhi") or "",
            "raag": n_meta.get("raag", ""),
            "writer": n_meta.get("writer", ""),
            "ang": n_meta.get("ang", 0),
            "tags": n_meta.get("tags", []),
            "is_repertoire": n_meta.get("is_repertoire", False),
            "primary_theme": n_meta.get("primary_theme", ""),
            "mood": n_meta.get("mood", ""),
            "brief_meaning": n_meta.get("brief_meaning") or n_sggs.get("brief_meaning") or "",
        }

        shared = set(n.get("shared_tags", []))
        n_all_tags = set(n_meta.get("tags", []))
        new_tags = n_all_tags - my_tags_set

        if shared == my_tags_set or not new_tags:
            for tag in shared:
                by_tag[tag].append(enriched)
        else:
            best_new = min(new_tags, key=lambda t: len(graph.get("tag_index", {}).get(t, [])))
            by_tag[best_new].append(enriched)

    # Cap each cluster, sorted by score
    for tag in by_tag:
        by_tag[tag].sort(key=lambda x: x["score"], reverse=True)
        by_tag[tag] = by_tag[tag][:per_tag_cap]

    by_tag = {tag: items for tag, items in by_tag.items() if items}

    all_scores = [n["score"] for n in raw_neighbors] if raw_neighbors else [0]
    if tuk_results:
        all_scores.extend(r["score"] for r in tuk_results.values())

    return jsonify({
        "id": shabad_id,
        "tags": my_tags,
        "by_tag": dict(by_tag),
        "total_available": len(raw_neighbors) + len(tuk_results),
        "total_shown": sum(len(v) for v in by_tag.values()),
        "score_range": {"min": round(min(all_scores), 3) if all_scores else 0, "max": round(max(all_scores), 3) if all_scores else 0},
        "tuk_search": bool(tuk_results),
    })


@graph_bp.route("/graph/shabads", methods=["POST"])
def get_shabads_by_ids():
    """Return full shabad data for an array of BaniDB IDs.

    Used by the reviewer to load complete shabad details (Gurmukhi text,
    translation, tags, themes) without depending on the personal library.
    """
    data = request.get_json()
    ids = [str(i) for i in data.get("ids", [])]

    graph = _get_graph()
    sggs_lookup = _get_sggs_lookup()
    metadata = graph.get("metadata", {})
    neighbors_map = graph.get("neighbors", {})

    results = []
    for sid in ids:
        meta = metadata.get(sid, {})
        sggs = sggs_lookup.get(sid, {})

        # Compute shared tags with next shabad in the list (for transition display)
        idx = ids.index(sid)
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
            "english_translation": sggs.get("english_translation") or "",
            "transliteration": sggs.get("transliteration") or "",
            "brief_meaning": sggs.get("brief_meaning") or "",
            "rahao_gurmukhi": sggs.get("rahao_gurmukhi") or "",
            "rahao_english": sggs.get("rahao_english") or "",
            "raag": meta.get("raag") or sggs.get("sggs_raag") or "",
            "writer": meta.get("writer") or sggs.get("writer") or "",
            "ang": meta.get("ang") or sggs.get("ang_number") or 0,
            "tags": meta.get("tags", []),
            "primary_theme": meta.get("primary_theme") or sggs.get("primary_theme") or "",
            "mood": meta.get("mood") or sggs.get("mood") or "",
            "is_repertoire": meta.get("is_repertoire", False),
            "shared_tags_with_next": shared_with_next,
        })

    return jsonify({"shabads": results})


@graph_bp.route("/graph/shabad/<shabad_id>/verses")
def get_shabad_verses_graph(shabad_id):
    """Return verse-level data for a shabad (via BaniDB cache)."""
    from enrichment.banidb_matcher import BaniDBMatcher

    sid = int(shabad_id) if shabad_id.isdigit() else 0
    if not sid:
        return jsonify({"verses": [], "rahao_index": -1})

    matcher = BaniDBMatcher()
    shabad_data = matcher.get_shabad(sid)
    matcher.close()

    if not shabad_data:
        return jsonify({"verses": [], "rahao_index": -1})

    verses = []
    rahao_index = -1
    for i, v in enumerate(shabad_data.get("verses", [])):
        translit = v.get("transliteration", {})
        eng_translit = translit.get("en", "") if isinstance(translit, dict) else ""

        translation = v.get("translation", {})
        en_trans = translation.get("en", {}) if isinstance(translation, dict) else {}
        if isinstance(en_trans, dict):
            eng = en_trans.get("bdb") or en_trans.get("ms") or en_trans.get("ssk") or ""
        else:
            eng = ""

        gurmukhi = v.get("verse", {})
        gur_text = gurmukhi.get("unicode", "") if isinstance(gurmukhi, dict) else ""

        is_rahao = "rahaau" in eng_translit.lower()
        if is_rahao and rahao_index == -1:
            rahao_index = i

        verses.append({
            "index": i,
            "transliteration": eng_translit,
            "english": eng,
            "gurmukhi": gur_text,
            "is_rahao": is_rahao,
        })

    return jsonify({
        "banidb_shabad_id": sid,
        "verses": verses,
        "rahao_index": rahao_index,
    })


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

    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

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
