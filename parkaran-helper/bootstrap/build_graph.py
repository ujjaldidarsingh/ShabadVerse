"""Precompute similarity graph from tagged SGGS shabads.

Scoring: IDF-weighted tag overlap (50%) + semantic embedding cosine (50%).
Tag overlap is weighted by log(N/count) so that sharing a rare, telling tag
counts for far more than sharing a corpus-wide one — plain Jaccard rated two
shabads "similar" merely for both carrying a broad theme.
Embeddings come from ChromaDB (ONNX all-MiniLM-L6-v2) for contextual meaning —
NOT TF-IDF, which can't distinguish "not worthy of love" from "worthy of love".
Repertoire is a visual marker, NOT a connector tag.
"""

import sys
import os
import json
import math
import numpy as np
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

GRAPH_PATH = os.path.join(config.DATA_DIR, "similarity_graph.json")

# Tags that are visual markers, not thematic connectors
NON_CONNECTOR_TAGS = {"Repertoire"}


def jaccard_similarity(set_a, set_b):
    """Plain Jaccard similarity between two sets (every tag counts equally)."""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def build_tag_idf(tag_index, n_shabads):
    """Inverse document frequency per tag: log(N / shabads-carrying-tag).

    A tag shared by half the corpus says almost nothing about why two shabads
    belong together; a tag shared by forty says a great deal. IDF encodes that.
    """
    return {
        tag: math.log(n_shabads / max(1, len(sids)))
        for tag, sids in tag_index.items()
    }


def weighted_jaccard(set_a, set_b, idf):
    """IDF-weighted Jaccard: sum(idf over shared) / sum(idf over union).

    Replaces plain Jaccard so that sharing a rare, telling tag ("Haumai", 184
    shabads) outweighs sharing a broad one ("Naam Simran", 2,033). Without this,
    two shabads that merely both mention the Divine score as "similar" as two
    that share a specific spiritual argument.
    """
    if not set_a or not set_b:
        return 0.0
    shared = set_a & set_b
    if not shared:
        return 0.0
    union = set_a | set_b
    shared_w = sum(idf.get(t, 0.0) for t in shared)
    union_w = sum(idf.get(t, 0.0) for t in union)
    return shared_w / union_w if union_w > 0 else 0.0


def embedding_cosine(vec_a, vec_b):
    """Cosine similarity between two embedding vectors."""
    dot = np.dot(vec_a, vec_b)
    norm = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    return float(dot / norm) if norm > 0 else 0.0


def load_embeddings():
    """Load all SGGS embeddings from ChromaDB. Returns {id_str: np.array}."""
    from database.vector_store import ShabadVectorStore

    print("Loading embeddings from ChromaDB...")
    store = ShabadVectorStore(collection_name=config.SGGS_COLLECTION_NAME)
    collection = store.collection

    # ChromaDB get() returns all items with their embeddings
    result = collection.get(include=["embeddings"])
    lookup = {}
    for sid, emb in zip(result["ids"], result["embeddings"]):
        lookup[str(sid)] = np.array(emb, dtype=np.float32)

    print(f"  Loaded {len(lookup)} embeddings ({lookup[next(iter(lookup))].shape[0]}-dim)")
    return lookup


def build_graph():
    """Build precomputed similarity graph."""
    print("=" * 60)
    print("  Building Similarity Graph (Embedding-Based)")
    print("=" * 60)

    # Load SGGS shabads
    with open(config.SGGS_DATA_PATH, encoding="utf-8") as f:
        sggs_shabads = json.load(f)

    tagged = [s for s in sggs_shabads if s.get("tags")]
    print(f"Tagged SGGS shabads: {len(tagged)}")

    if len(tagged) < 100:
        print("Not enough tagged shabads. Run build_concept_tags.py first.")
        return

    # Load sentence-transformer embeddings
    embedding_lookup = load_embeddings()

    # Build connector tag sets (exclude Repertoire). Every shabad gets an entry;
    # under the concept taxonomy ~10% carry no tag and connect by embedding alone.
    shabad_tags = {}
    repertoire_ids = set()
    presentation_tags = {}

    for s in sggs_shabads:
        sid = str(s["banidb_shabad_id"])
        all_tags = set(s.get("tags") or [])
        connector_tags = all_tags - NON_CONNECTOR_TAGS
        shabad_tags[sid] = connector_tags
        presentation_tags[sid] = [t for t in s.get("presentation_tags", sorted(connector_tags)) if t in connector_tags]
        if "Repertoire" in all_tags:
            repertoire_ids.add(sid)

    print(f"  Repertoire shabads: {len(repertoire_ids)}")

    # Build inverted index from CONNECTOR tags only
    print("\nBuilding tag index...")
    tag_index = defaultdict(list)
    for sid, tags in shabad_tags.items():
        for tag in sorted(tags):
            tag_index[tag].append(sid)

    tag_index = dict(tag_index)
    print(f"  Connector tags: {len(tag_index)}")
    print(f"  Avg shabads per tag: {sum(len(v) for v in tag_index.values()) / max(1, len(tag_index)):.0f}")

    # IDF weights make edge scores reflect *why* two shabads connect, not just
    # that they both carry a corpus-wide theme.
    tag_idf = build_tag_idf(tag_index, len(shabad_tags))
    _rarest = sorted(tag_idf.items(), key=lambda kv: -kv[1])[:3]
    _commonest = sorted(tag_idf.items(), key=lambda kv: kv[1])[:3]
    print(f"  IDF range: {_commonest[0][0]}={_commonest[0][1]:.2f} ... {_rarest[0][0]}={_rarest[0][1]:.2f}")

    # Build k-NN graph: tag-balanced neighbor selection
    # For each shabad, allocate slots per tag to ensure ALL tags get representation
    print("\nComputing tag-balanced similarity (Jaccard + embeddings)...")
    K_MAX = 40  # Increased from 20 — more data stored, filtered at query time
    PER_TAG_MIN = 3  # Every distinctive tag gets at least 3 neighbors
    MEGA_TAG_COVERAGE = 0.25  # tag on >25% of corpus = structural, not a connector
    MEGA_TAG_SLOTS = 1  # structural tags get a token slot, not a full quota
    neighbors = {}
    TAG_WEIGHT = 0.5
    EMBED_WEIGHT = 0.5

    sids = list(shabad_tags.keys())
    total = len(sids)
    embed_hits = 0
    embed_misses = 0
    empty_tag_clusters = 0

    for i, sid in enumerate(sids):
        if i % 500 == 0:
            print(f"  Processing {i}/{total}...")

        my_tags = shabad_tags[sid]
        my_emb = embedding_lookup.get(sid)
        n_tags = len(my_tags)

        if n_tags == 0:
            neighbors[sid] = []
            continue

        # Score candidates per tag with BRANCHING diversity
        # For each tag, find two pools:
        #   1. "core" — shares this tag + high embedding similarity (the obvious matches)
        #   2. "branching" — shares this tag but brings DIFFERENT other tags (the surprises)
        per_tag_candidates = {}  # {tag: [(cid, score, shared_tags), ...]}

        for tag in presentation_tags[sid]:
            tag_candidates = tag_index.get(tag, [])
            core_pool = []     # High overlap candidates
            branch_pool = []   # Different-direction candidates

            for cid in tag_candidates:
                if cid == sid:
                    continue
                their_tags = shabad_tags.get(cid, set())
                shared = my_tags & their_tags
                different = their_tags - my_tags  # Tags they have that we don't

                embed_sim = 0.0
                if my_emb is not None:
                    their_emb = embedding_lookup.get(cid)
                    if their_emb is not None:
                        embed_sim = embedding_cosine(my_emb, their_emb)
                        embed_hits += 1
                    else:
                        embed_misses += 1
                else:
                    embed_misses += 1

                # Core score: IDF-weighted tag overlap + embedding.
                # Weighted (not plain) Jaccard so a shared rare tag counts for
                # more than a shared corpus-wide one.
                tag_sim = weighted_jaccard(my_tags, their_tags, tag_idf)
                core_score = TAG_WEIGHT * tag_sim + EMBED_WEIGHT * embed_sim

                # Branching score: embedding similarity + bonus for bringing new tags
                # A candidate that shares 1 tag but has 2 different tags gets a diversity boost
                diversity_bonus = min(len(different) * 0.1, 0.3)  # Up to +0.3 for new tags
                branch_score = max(0.0, min(1.0, (embed_sim * 0.7 + diversity_bonus + 0.1) / 1.1))  # base relevance

                shared_list = sorted(shared)

                if len(shared) == len(my_tags):
                    # Shares ALL our tags — core candidate (same direction)
                    if core_score > 0.05:
                        core_pool.append((cid, round(core_score, 3), shared_list))
                else:
                    # Shares SOME but not all — branching candidate (different direction)
                    if branch_score > 0.15:
                        branch_pool.append((cid, round(branch_score, 3), shared_list))

            core_pool.sort(key=lambda x: (-x[1], x[0]))
            branch_pool.sort(key=lambda x: (-x[1], x[0]))

            # Merge: take top core + top branching
            # Guarantees branching neighbors per tag for genuine variety
            merged = []
            n_core = min(len(core_pool), 4)   # Max 4 "same direction" per tag
            n_branch = max(4, 8 - n_core)     # Rest is branching — aim for 8 per tag total
            merged.extend(core_pool[:n_core])
            merged.extend(branch_pool[:n_branch])
            merged.sort(key=lambda x: (-x[1], x[0]))

            per_tag_candidates[tag] = merged

            if not merged:
                empty_tag_clusters += 1

        # Allocate slots: each tag gets max(PER_TAG_MIN, K_MAX / n_tags) slots.
        # Exception: a structural tag (carried by >MEGA_TAG_COVERAGE of the
        # corpus) gets a single slot. Giving it the full quota guaranteed that
        # every shabad carrying it received neighbors linked by nothing else —
        # the mega-tag pool is enormous, so those edges said only "both of these
        # mention the Divine". Distinctive tags earn the remaining slots.
        slots_per_tag = max(PER_TAG_MIN, K_MAX // n_tags)
        selected = {}  # cid -> {score, shared_tags} (deduplicated, keep best score)

        for tag, candidates in per_tag_candidates.items():
            is_mega = len(tag_index.get(tag, [])) > MEGA_TAG_COVERAGE * total
            tag_slots = MEGA_TAG_SLOTS if is_mega else slots_per_tag
            for cid, score, shared in candidates[:tag_slots]:
                if cid in selected:
                    # Keep the higher score, merge shared tags
                    if score > selected[cid]["score"]:
                        selected[cid]["score"] = score
                    selected[cid]["shared_tags"] = list(
                        set(selected[cid]["shared_tags"]) | set(shared)
                    )
                else:
                    selected[cid] = {"score": score, "shared_tags": shared}

        # Sort by score, cap at K_MAX
        final = sorted(
            [{"id": cid, **data} for cid, data in selected.items()],
            key=lambda x: (-x["score"], x["id"]),
        )[:K_MAX]

        neighbors[sid] = final

    print(f"  Embedding comparisons: {embed_hits:,} hits, {embed_misses:,} misses")
    print(f"  Empty tag clusters avoided: {empty_tag_clusters} (tags with 0 candidates)")

    # Untagged shabads still get neighbors — pure embedding cosine, since there
    # are no tags to share. Score is the raw cosine (comparable in magnitude to
    # tagged edge scores), shared_tags empty by construction.
    EMBED_ONLY_K = 12
    untagged_sids = [s for s in sids if not shabad_tags[s]]
    if untagged_sids:
        emb_sids = [s for s in sids if embedding_lookup.get(s) is not None]
        matrix = np.asarray([embedding_lookup[s] for s in emb_sids], dtype=np.float32)
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
        row_of = {s: i for i, s in enumerate(emb_sids)}
        filled = 0
        for sid in untagged_sids:
            row = row_of.get(sid)
            if row is None:
                continue
            scores = matrix @ matrix[row]
            entries = []
            for j in np.argsort(scores)[::-1][: EMBED_ONLY_K + 1]:
                cid = emb_sids[j]
                if cid == sid:
                    continue
                entries.append(
                    {"id": cid, "score": round(float(scores[j]), 3), "shared_tags": []}
                )
                if len(entries) >= EMBED_ONLY_K:
                    break
            neighbors[sid] = entries
            filled += 1
        print(f"  Embedding-only neighbors for {filled}/{len(untagged_sids)} untagged shabads")

    # Build metadata with brief_meaning included — over ALL shabads, so untagged
    # ones still resolve for previews, search hits, and line-mode neighbors.
    print("\nBuilding metadata index...")
    metadata = {}
    for s in sggs_shabads:
        sid = str(s["banidb_shabad_id"])
        metadata[sid] = {
            "title": s.get("display_name") or (s.get("transliteration") or "")[:80],
            "gurmukhi": s.get("display_gurmukhi") or "",
            "raag": s.get("sggs_raag", ""),
            "writer": s.get("writer", ""),
            "ang": s.get("ang_number", 0),
            "tags": [t for t in s.get("tags", []) if t not in NON_CONNECTOR_TAGS],
            "is_repertoire": sid in repertoire_ids,
            "primary_theme": s.get("primary_theme", ""),
            "mood": s.get("mood", ""),
            "brief_meaning": s.get("brief_meaning", ""),
        }

    # Save graph
    graph = {
        "version": "5.0",
        "scoring": "Core: 0.5 IDF Jaccard + 0.5 cosine; branch: (0.7 cosine + diversity + 0.1) / 1.1; untagged: cosine. Ranking heuristics, not confidence.",
        "k_max": K_MAX,
        "per_tag_min": PER_TAG_MIN,
        "stats": {
            "total_shabads": len(neighbors),
            "sggs_shabads": len(tagged),
            "tags_count": len(tag_index),
            "repertoire_count": len(repertoire_ids),
            "avg_neighbors": round(sum(len(v) for v in neighbors.values()) / max(1, len(neighbors)), 1),
        },
        "neighbors": neighbors,
        "tag_index": tag_index,
        "repertoire": list(repertoire_ids),
        "metadata": metadata,
    }

    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(GRAPH_PATH, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False)

    file_size_mb = os.path.getsize(GRAPH_PATH) / (1024 * 1024)
    print(f"\nSaved graph to {GRAPH_PATH} ({file_size_mb:.1f} MB)")
    print(f"  Shabads: {len(neighbors)}")
    print(f"  Connector tags: {len(tag_index)} (Repertoire excluded)")
    print(f"  Repertoire: {len(repertoire_ids)}")
    print(f"  Avg neighbors: {graph['stats']['avg_neighbors']}")

    print("\nTop 20 connector tags:")
    sorted_tags = sorted(tag_index.items(), key=lambda x: len(x[1]), reverse=True)
    for tag, sids_list in sorted_tags[:20]:
        print(f"  {len(sids_list):5d} - {tag}")


if __name__ == "__main__":
    from bootstrap.build_guard import require_build_target
    require_build_target(legacy=False)
    build_graph()
