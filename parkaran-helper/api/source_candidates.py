"""Retrieve source-scoped candidates from preserved whole-shabad vectors."""
import threading
import numpy as np

_lock = threading.Lock()
_index = None


def vectors(store):
    global _index
    with _lock:
        if _index is None:
            ids, chunks = [], []
            for offset in range(0, store.get_count(), 1000):
                page = store.collection.get(limit=1000, offset=offset, include=['embeddings'])
                ids.extend(page['ids']); chunks.extend(page['embeddings'])
            matrix = np.asarray(chunks, dtype=np.float32)
            matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9)
            _index = (ids, matrix, {sid: i for i, sid in enumerate(ids)})
    return _index


def retrieve(store, seed, eligible, metadata, overlap, query='', limit=30):
    ids, matrix, row = vectors(store)
    if seed not in row:
        return []
    if query:
        # search_similar validates the complete offline model cache first.
        store.search_similar(query, n_results=1)
        vector = np.asarray(store.embedding_fn([query])[0], dtype=np.float32)
        vector /= max(float(np.linalg.norm(vector)), 1e-9)
    else:
        vector = matrix[row[seed]]
    scores = matrix @ vector
    seed_tags = metadata[seed].get('tags', [])
    result = []
    for sid in eligible:
        if sid == seed or sid not in row or sid not in metadata:
            continue
        cosine = float(np.clip(scores[row[sid]], 0, 1))
        tags = metadata[sid].get('tags', [])
        score = cosine if query or not seed_tags else .5 * cosine + .5 * overlap(seed_tags, tags)
        result.append({'id': sid, 'score': round(score, 3), 'shared_tags': sorted(set(seed_tags) & set(tags))})
    return sorted(result, key=lambda n: (-n['score'], n['id']))[:limit]
