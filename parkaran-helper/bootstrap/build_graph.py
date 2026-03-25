"""Precompute similarity graph from tagged SGGS shabads.

Scoring: tag overlap (Jaccard, 50%) + semantic embedding cosine (50%).
Uses sentence-transformer embeddings from ChromaDB for contextual meaning —
NOT TF-IDF, which can't distinguish "not worthy of love" from "worthy of love".
Repertoire is a visual marker, NOT a connector tag.
"""

import sys
import os
import json
import numpy as np
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

GRAPH_PATH = os.path.join(config.DATA_DIR, "similarity_graph.json")

# Tags that are visual markers, not thematic connectors
NON_CONNECTOR_TAGS = {"Repertoire"}


def jaccard_similarity(set_a, set_b):
    """Jaccard similarity between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


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
        print("Not enough tagged shabads. Run tag_shabads.py first.")
        return

    # Load sentence-transformer embeddings
    embedding_lookup = load_embeddings()

    # Build connector tag sets (exclude Repertoire)
    shabad_tags = {}
    repertoire_ids = set()

    for s in tagged:
        sid = str(s["banidb_shabad_id"])
        all_tags = set(s["tags"])
        connector_tags = all_tags - NON_CONNECTOR_TAGS
        shabad_tags[sid] = connector_tags
        if "Repertoire" in all_tags:
            repertoire_ids.add(sid)

    print(f"  Repertoire shabads: {len(repertoire_ids)}")

    # Build inverted index from CONNECTOR tags only
    print("\nBuilding tag index...")
    tag_index = defaultdict(list)
    for sid, tags in shabad_tags.items():
        for tag in tags:
            tag_index[tag].append(sid)

    tag_index = dict(tag_index)
    print(f"  Connector tags: {len(tag_index)}")
    print(f"  Avg shabads per tag: {sum(len(v) for v in tag_index.values()) / max(1, len(tag_index)):.0f}")

    # Build k-NN graph: tag-balanced neighbor selection
    # For each shabad, allocate slots per tag to ensure ALL tags get representation
    print("\nComputing tag-balanced similarity (Jaccard + embeddings)...")
    K_MAX = 40  # Increased from 20 — more data stored, filtered at query time
    PER_TAG_MIN = 3  # Every tag gets at least 3 neighbors
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

        # Score ALL candidates per tag (not globally)
        # This prevents dominant tags from starving minority tags
        per_tag_candidates = {}  # {tag: [(cid, score, shared_tags), ...]}

        for tag in my_tags:
            tag_candidates = tag_index.get(tag, [])
            scored_for_tag = []

            for cid in tag_candidates:
                if cid == sid:
                    continue
                their_tags = shabad_tags.get(cid, set())
                tag_sim = jaccard_similarity(my_tags, their_tags)

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

                score = TAG_WEIGHT * tag_sim + EMBED_WEIGHT * embed_sim
                shared = list(my_tags & their_tags)

                if score > 0.05:
                    scored_for_tag.append((cid, round(score, 3), shared))

            scored_for_tag.sort(key=lambda x: x[1], reverse=True)
            per_tag_candidates[tag] = scored_for_tag

            if not scored_for_tag:
                empty_tag_clusters += 1

        # Allocate slots: each tag gets max(PER_TAG_MIN, K_MAX / n_tags) slots
        slots_per_tag = max(PER_TAG_MIN, K_MAX // n_tags)
        selected = {}  # cid -> {score, shared_tags} (deduplicated, keep best score)

        for tag, candidates in per_tag_candidates.items():
            for cid, score, shared in candidates[:slots_per_tag]:
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
            key=lambda x: x["score"],
            reverse=True,
        )[:K_MAX]

        neighbors[sid] = final

    print(f"  Embedding comparisons: {embed_hits:,} hits, {embed_misses:,} misses")
    print(f"  Empty tag clusters avoided: {empty_tag_clusters} (tags with 0 candidates)")

    # Build metadata with brief_meaning included
    print("\nBuilding metadata index...")
    metadata = {}
    for s in tagged:
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
        "version": "4.0",
        "scoring": "50% Jaccard + 50% embedding cosine, tag-balanced allocation",
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
    build_graph()
