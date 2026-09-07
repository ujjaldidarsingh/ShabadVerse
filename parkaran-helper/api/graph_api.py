"""Graph API endpoints for the interactive explorer."""

import json
import math
import os
from collections import defaultdict
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
_sggs_sources = None

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
    """Lazy-load SGGS ChromaDB vector store for tuk-aware search."""
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
# Two matching algorithms answer two different questions:
#
#   match=shabad  "Which shabads are ABOUT the same things as this one?"
#                 Precomputed: IDF-weighted tag Jaccard (50%) + shabad-summary
#                 embedding cosine (50%). The unit of meaning is the whole shabad.
#
#   match=line    "Where else does THIS thought appear?"
#                 Live: line-embedding cosine dominates; whole-shabad tags are
#                 only a weak prior. The unit of meaning is the single tuk.
#
# The weights below are the substance of the difference. If tags were weighted
# heavily in line mode, line mode would collapse back into shabad mode: the
# container's themes would drown out the line's own meaning. Conversely a pure
# line-cosine with no tag prior surfaces lexically-close lines from shabads with
# no spiritual relationship. 85/15 keeps the line in charge while letting the
# container break ties.
LINE_EMBED_WEIGHT = 0.85
LINE_TAG_PRIOR_WEIGHT = 0.15

# A candidate line that is its own shabad's rahao carries more weight: that
# thought is the shabad's thesis, not a passing phrase.
LINE_RAHAO_BONUS = 0.05

# Over-fetch lines so that after collapsing to one line per shabad we still have
# a full neighbor set. Long shabads would otherwise crowd out whole shabads.
LINE_FETCH_MULTIPLIER = 12


def _weighted_jaccard(tags_a, tags_b, tag_index, n_shabads):
    """IDF-weighted overlap of two tag sets. Mirrors bootstrap/build_graph.py so
    the tag prior in line mode is on the same scale as shabad mode's tag term."""
    set_a, set_b = set(tags_a or []), set(tags_b or [])
    shared = set_a & set_b
    if not shared:
        return 0.0
    union = set_a | set_b

    def idf(tag):
        return math.log(max(1, n_shabads) / max(1, len(tag_index.get(tag, []))))

    union_w = sum(idf(t) for t in union)
    return (sum(idf(t) for t in shared) / union_w) if union_w > 0 else 0.0


def _resolve_anchor_line(shabad_id, line_index):
    """Pick the line whose meaning drives a line-mode expansion.

    Explicit choice wins. Otherwise the rahao: it is the shabad's own statement
    of what it is about, so it is the most faithful default anchor. Failing that
    (saloks carry no rahao), the first substantive line — structural headers like
    "ਮਹਲਾ ੪ ॥" never enter the collection, so index order already skips them.

    Returns (line_index, english, gurmukhi) or None when the shabad has no
    embeddable lines at all.
    """
    store = _get_lines_vector_store()
    got = store.collection.get(where={"shabad_id": str(shabad_id)})
    metas = got.get("metadatas") or []
    if not metas:
        return None

    by_index = {m["line_index"]: m for m in metas}

    if line_index is not None:
        if line_index not in by_index:
            return None
        chosen = by_index[line_index]
    else:
        rahao = [m for m in metas if m.get("is_rahao")]
        chosen = rahao[0] if rahao else by_index[min(by_index)]

    return chosen["line_index"], chosen["english"], chosen.get("gurmukhi", "")


def _line_neighbors(shabad_id, line_index, limit, threshold, metadata, tag_index, eligible_ids=None):
    """Find shabads containing a line semantically closest to the anchor line.

    Returns (results, anchor) where results is a list of dicts carrying the
    matched line, and anchor describes the line we searched from.
    """
    anchor = _resolve_anchor_line(shabad_id, line_index)
    if not anchor:
        return [], None
    anchor_idx, anchor_english, anchor_gurmukhi = anchor

    store = _get_lines_vector_store()
    if store.get_count() == 0:
        return [], None

    my_tags = metadata.get(str(shabad_id), {}).get("tags", [])
    n_shabads = len(metadata) or 1

    if eligible_ids is not None and not eligible_ids:
        return [], {"line_index": anchor_idx, "english": anchor_english, "gurmukhi": anchor_gurmukhi}
    where = {"shabad_id": {"$in": sorted(eligible_ids)}} if eligible_ids is not None else None
    raw = store.search_similar(anchor_english, n_results=limit * LINE_FETCH_MULTIPLIER, where_filter=where)

    # Collapse to the single best line per shabad. Without this a long shabad
    # that echoes the anchor across eight verses would occupy eight slots.
    best_per_shabad = {}
    seen_text = set()
    for match in raw:
        meta = match.get("metadata") or {}
        cid = str(meta.get("shabad_id", ""))
        if not cid or cid == str(shabad_id):
            continue

        english = (meta.get("english") or "").strip()
        # Refrains repeat verbatim across shabads; one instance is informative,
        # ten are noise.
        text_key = english.lower()
        if text_key in seen_text:
            continue

        distance = match.get("distance")
        line_cos = max(0.0, 1.0 - distance) if distance is not None else 0.0
        tag_prior = _weighted_jaccard(my_tags, metadata.get(cid, {}).get("tags", []), tag_index, n_shabads)

        score = LINE_EMBED_WEIGHT * line_cos + LINE_TAG_PRIOR_WEIGHT * tag_prior
        if meta.get("is_rahao"):
            score = min(1.0, score + LINE_RAHAO_BONUS)

        prev = best_per_shabad.get(cid)
        if prev is None or score > prev["score"]:
            if prev is not None:
                seen_text.discard(prev["matched_line_english"].lower())
            best_per_shabad[cid] = {
                "id": cid,
                "score": round(score, 3),
                "line_score": round(line_cos, 3),
                "matched_line_index": meta.get("line_index"),
                "matched_line_gurmukhi": meta.get("gurmukhi", ""),
                "matched_line_english": english,
                "matched_line_is_rahao": bool(meta.get("is_rahao")),
            }
            seen_text.add(text_key)

    results = [r for r in best_per_shabad.values() if r["score"] >= threshold]
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit], {
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


def _get_sggs_sources() -> dict[str, dict]:
    """Lazy-load shabad source flags (Amrit Keertan today, others later).

    Maps shabad_id -> {amrit_keertan: bool, ak_chapters: list[int], ...}.
    Built by bootstrap/index_amrit_keertan.py from BaniDB. Returns an empty
    dict if the file isn't present (graceful degradation — AK boost just
    becomes a no-op when source data is missing).
    """
    global _sggs_sources
    if _sggs_sources is None:
        path = os.path.join(config.DATA_DIR, "sggs_sources.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _sggs_sources = json.load(f)
        else:
            _sggs_sources = {}
    return _sggs_sources


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


@graph_bp.route("/graph/neighbors/<shabad_id>")
def graph_neighbors(shabad_id):
    """Return neighbors for a shabad, grouped by shared tag.

    Query params:
        threshold (float): Min score to include (default 0.3)
        per_tag (int): Max neighbors per tag cluster (default 8)
        match (str): "shabad" (default) or "line". See the Line matching section
            above — these are two different algorithms answering two different
            questions, not one algorithm with a filter.
        line_index (int): in match=line, anchor on this verse. Defaults to the
            shabad's rahao, then its opening line.
    """
    graph = _get_graph()
    sggs_lookup = _get_sggs_lookup()
    sources = _get_sggs_sources()
    metadata = graph.get("metadata", {})

    threshold = request.args.get("threshold", 0.3, type=float)
    if not math.isfinite(threshold):
        return jsonify({"error": "Invalid threshold"}), 400
    threshold = max(0.0, min(threshold, 1.0))
    per_tag_cap = max(1, min(request.args.get("per_tag", 8, type=int), 30))
    max_neighbors = max(1, min(request.args.get("max_neighbors", 30, type=int), 60))
    tuk_english = request.args.get("tuk_english", "", type=str).strip()[:2000]
    match_mode = request.args.get("match", "shabad", type=str).lower()
    if match_mode not in ("shabad", "line"):
        match_mode = "shabad"
    line_index = request.args.get("line_index", type=int)
    # AK boost: when on, multiply AK-flagged neighbor scores by AK_BOOST_FACTOR
    # before threshold-filtering and per-tag sort. This lifts canonically-recited
    # shabads in the recommendation order without excluding non-AK matches.
    ak_boost = request.args.get("ak_boost", "", type=str).lower() in ("1", "true", "yes")

    source_mode = request.args.get('source', 'prefer-ak' if ak_boost else 'all')
    if source_mode not in ('all', 'prefer-ak', 'ak-only'):
        return jsonify({'error': 'Unknown source mode'}), 400
    if source_mode != 'all' and not sources:
        return jsonify({'error': 'Amrit Keertan source index is unavailable'}), 503
    ak_ids = {sid for sid, value in sources.items() if value.get('amrit_keertan') and sid in metadata}

    if str(shabad_id) not in metadata:
        return jsonify({"error": "Shabad not found"}), 404
    requested_match = match_mode
    fallback_reason = None

    def is_ak(nid: str) -> bool:
        return bool(sources.get(str(nid), {}).get("amrit_keertan"))

    # Get this shabad's tags from graph metadata
    my_meta = metadata.get(str(shabad_id), {})
    my_tags = my_meta.get("tags", [])

    # ── BLENDED PATH: tuk vector search + graph neighbors for tag diversity ──
    # When tuk_english is provided, vector search finds semantically close shabads
    # to the specific verse. Graph neighbors fill in tag-based diversity.
    # When no tuk, pure graph path (pre-computed, instant).
    tuk_results = {}  # nid -> enriched dict (from vector search)
    if tuk_english and match_mode == "shabad":
        store = _get_sggs_vector_store()
        if store.get_count() > 0:
            results = store.search_similar(
                tuk_english, n_results=30, exclude_ids={str(shabad_id)}
            )
            for r in results:
                nid = str(r["id"])
                n_meta = metadata.get(nid, {})
                n_sggs = sggs_lookup.get(nid, {})
                distance = r.get("distance")
                base_score = max(0, min(1, 1 - distance)) if distance is not None else 0.0
                score = base_score
                if score < threshold or (source_mode == "ak-only" and not is_ak(nid)):
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
                    "is_repertoire": False,
                    "is_amrit_keertan": is_ak(nid),
                    "primary_theme": n_meta.get("primary_theme") or r["metadata"].get("primary_theme", ""),
                    "mood": n_meta.get("mood") or r["metadata"].get("mood", ""),
                    "brief_meaning": n_meta.get("brief_meaning") or n_sggs.get("brief_meaning") or r["metadata"].get("brief_meaning", ""),
                }

    tag_index = graph.get("tag_index", {})
    line_anchor = None
    line_info = {}  # nid -> matched-line detail, merged into the enriched neighbor

    if match_mode == "line":
        # ── LINE PATH: live per-verse search ──
        # Neighbors are the shabads whose closest line most resembles our anchor
        # line, scored by line-embedding cosine with the container's tags as a
        # weak prior. Shaped like precomputed neighbors so the clustering,
        # AK-boost and enrichment below need no special-casing.
        hits, line_anchor = _line_neighbors(
            shabad_id, line_index, 30, threshold, metadata, tag_index,
            eligible_ids=ak_ids if source_mode == "ak-only" else None
        )
        if source_mode == 'prefer-ak':
            source_hits, _ = _line_neighbors(shabad_id, line_index, 30, threshold, metadata, tag_index, eligible_ids=ak_ids)
            hits = list({hit['id']: hit for hit in hits + source_hits}.values())
        raw_neighbors = []
        for hit in hits:
            nid = hit["id"]
            line_info[nid] = hit
            shared = list(set(my_tags) & set(metadata.get(nid, {}).get("tags", [])))
            raw_neighbors.append({"id": nid, "score": hit["score"], "shared_tags": shared})

        if not raw_neighbors:
            # A handful of shabads carry no embeddable lines (headers only), and
            # a strict threshold can filter everything out. Never hand back an
            # empty expansion — fall back to the shabad-level graph.
            match_mode = "shabad"
            fallback_reason = "No matching indexed lines at this threshold; showing whole-shabad connections."
            line_anchor = None
            line_info = {}
            raw_neighbors = graph.get("neighbors", {}).get(str(shabad_id), [])
    else:
        # ── GRAPH PATH: pre-computed shabad-level neighbors ──
        raw_neighbors = graph.get("neighbors", {}).get(str(shabad_id), [])

    if source_mode != 'all' and match_mode == 'shabad':
        from api.source_candidates import retrieve
        extra = retrieve(_get_sggs_vector_store(), str(shabad_id), ak_ids, metadata,
                         lambda x, y: _weighted_jaccard(x, y, tag_index, len(metadata)),
                         query=tuk_english)
        # Preserve the graph's score for existing edges; add newly retrieved AK edges.
        merged = {n['id']: n for n in extra}
        merged.update({n['id']: n for n in raw_neighbors})
        raw_neighbors = list(merged.values())
    neighbors = [n for n in raw_neighbors if n['score'] >= threshold and
                 (source_mode != 'ak-only' or is_ak(n['id']))]

    # Group neighbors by thematic direction
    my_tags_set = set(my_tags)
    by_tag = defaultdict(list)
    seen_globally = set()
    n_shabads = len(metadata) or 1

    # First: add tuk vector results (semantically closest to searched verse)
    for nid, enriched in tuk_results.items():
        seen_globally.add(nid)
        tags = enriched.get("tags", [])
        if not tags:
            by_tag["Translation similarity"].append(enriched)
            continue
        # Place under the most distinctive tag this neighbor shares with us
        matching_tags = [t for t in tags if t in my_tags_set]
        if matching_tags:
            by_tag[_pick_cluster_tag(matching_tags, tag_index, n_shabads)].append(enriched)
        else:
            # Branching: use the neighbor's most specific tag
            n_all_tags = set(tags)
            new_tags = n_all_tags - my_tags_set
            if new_tags:
                by_tag[_pick_cluster_tag(list(new_tags), tag_index, n_shabads)].append(enriched)
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
            "is_repertoire": False,
            "is_amrit_keertan": is_ak(nid),
            "primary_theme": n_meta.get("primary_theme", ""),
            "mood": n_meta.get("mood", ""),
            "brief_meaning": n_meta.get("brief_meaning") or n_sggs.get("brief_meaning") or "",
        }
        # In line mode, carry the verse that actually matched so the UI can show
        # WHY this shabad surfaced rather than just that it did.
        if nid in line_info:
            hit = line_info[nid]
            enriched.update({
                "matched_line_index": hit["matched_line_index"],
                "matched_line_gurmukhi": hit["matched_line_gurmukhi"],
                "matched_line_english": hit["matched_line_english"],
                "matched_line_is_rahao": hit["matched_line_is_rahao"],
                "line_score": hit["line_score"],
            })

        shared = set(n.get("shared_tags", []))
        n_all_tags = set(n_meta.get("tags", []))
        new_tags = n_all_tags - my_tags_set

        if shared == my_tags_set or not new_tags:
            # Same thematic direction. Title the cluster with the most
            # distinctive shared tag — one cluster, not one per shared tag,
            # which previously scattered a single neighbor across every
            # broad theme it happened to carry.
            label = _pick_cluster_tag(list(shared), tag_index, n_shabads)
        else:
            label = _pick_cluster_tag(list(new_tags), tag_index, n_shabads)

        # Line mode can surface a shabad sharing no tags at all — that is the
        # point (the same thought in an unrelated container). Give it a home.
        if not label:
            label = (
                _pick_cluster_tag(list(n_all_tags), tag_index, n_shabads)
                or "Translation similarity"
            )
        by_tag[label].append(enriched)

    # Bound the source-expanded view globally, preserving unmodified similarity.
    def ranking(n):
        return n['score'] + (.15 if source_mode == 'prefer-ak' and n['is_amrit_keertan'] else 0)
    if source_mode != 'all' or sum(map(len, by_tag.values())) > max_neighbors:
        chosen = sorted((n for group in by_tag.values() for n in group), key=lambda n: (-ranking(n), n['id']))[:max_neighbors]
        keep = {n['id'] for n in chosen}
        by_tag = {tag: [n for n in group if n['id'] in keep] for tag, group in by_tag.items()}
    for group in by_tag.values():
        for n in group:
            n['rank_score'] = round(ranking(n), 3)
            n['source_preferred'] = source_mode == 'prefer-ak' and n['is_amrit_keertan']
            n['ak_chapters'] = sources.get(n['id'], {}).get('ak_chapters', [])
    # Cap each cluster, sorted by score
    for tag in by_tag:
        by_tag[tag].sort(key=lambda x: (-x["rank_score"], x["id"]))
        by_tag[tag] = by_tag[tag][:per_tag_cap]

    # Keep small clusters truthful. A visual grouping must not invent a concept.
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
        "score_range": {
            "min": round(min(all_scores), 3) if all_scores else 0,
            "max": round(max(all_scores), 3) if all_scores else 0,
            "median": round(sorted(all_scores)[len(all_scores) // 2], 3) if all_scores else 0,
        },
        "source_mode": source_mode,
        "source_counts": {"ak": sum(n['is_amrit_keertan'] for group in by_tag.values() for n in group),
                          "shown": sum(len(group) for group in by_tag.values())},
        "source_notice": ('No Amrit Keertan connections at this setting. Lower selectivity or choose All SGGS.'
                          if source_mode == 'ak-only' and not by_tag else ''),
        "threshold_used": threshold,
        "tuk_search": bool(tuk_results),
        "match": match_mode,
        "requested_match": requested_match,
        "fallback_reason": fallback_reason,
        "score_kind": "ranking heuristic, not interpretive confidence",
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
            "is_amrit_keertan": bool(_get_sggs_sources().get(sid, {}).get('amrit_keertan')),
            "ak_chapters": _get_sggs_sources().get(sid, {}).get('ak_chapters', []),
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
    source = _get_sggs_sources().get(str(shabad_id), {})
    data['is_amrit_keertan'] = bool(source.get('amrit_keertan'))
    data['ak_chapters'] = source.get('ak_chapters', [])
    return jsonify(data)


@graph_bp.route("/graph/search")
def graph_search():
    """Search first letters entirely within the local scripture snapshot."""
    q = request.args.get("q", "").strip()[:200]
    searchtype = request.args.get("searchtype", 0, type=int)
    if searchtype not in (0, 1):
        return jsonify({"error": "Use searchtype 0 (start) or 1 (anywhere)"}), 400
    return jsonify(corpus.search(q, searchtype))


@graph_bp.route("/graph/semantic-search")
def graph_semantic_search():
    """Natural-language search: embed a free-text phrase and return the SGGS
    shabads whose meaning is closest.

    Lets a user describe what they're thinking of ("someone who walks the path
    and inspires others to walk it") and get a ranked set of shabads by meaning,
    not by first-letters. Rides on the same ONNX MiniLM embedder + ChromaDB
    SGGS collection used by the tuk-aware neighbor path.

    Query params:
        q (str): the natural-language phrase (min 3 chars)
        limit (int): max results (default 10, capped 25)
    """
    q = request.args.get("q", "").strip()[:2000]
    limit = max(1, min(request.args.get("limit", 10, type=int), 25))

    if not q or len(q) < 3:
        return jsonify([])

    store = _get_sggs_vector_store()
    if store.get_count() == 0:
        return jsonify([])

    sggs_lookup = _get_sggs_lookup()
    metadata = _get_graph().get("metadata", {})

    matches = store.search_similar(q, n_results=limit)
    results = []
    for m in matches:
        sid = str(m["id"])
        s = sggs_lookup.get(sid, {})
        meta = metadata.get(sid, {})
        # Cosine distance → similarity (ChromaDB uses cosine space here).
        distance = m.get("distance")
        score = round(max(0.0, 1.0 - distance), 3) if distance is not None else None
        results.append({
            "banidb_shabad_id": sid,
            "title_gurmukhi": s.get("display_gurmukhi") or s.get("gurmukhi_text", "")[:60] or meta.get("gurmukhi", ""),
            "title_transliteration": s.get("display_name") or s.get("transliteration", "")[:80] or meta.get("title", ""),
            "first_line_translation": s.get("brief_meaning") or s.get("rahao_english") or "",
            "ang_number": s.get("ang_number") or meta.get("ang") or 0,
            "raag": s.get("sggs_raag") or meta.get("raag", ""),
            "writer": (corpus.shabad(sid) or {}).get("writer", ""),
            "primary_theme": s.get("primary_theme") or meta.get("primary_theme", ""),
            "score": score,
        })

    return jsonify(results)


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
