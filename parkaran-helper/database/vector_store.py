"""ChromaDB vector store for semantic shabad search."""

import time
import chromadb
import voyageai
import config


class VoyageEmbeddingFunction(chromadb.EmbeddingFunction):
    """Custom embedding function using Voyage AI."""

    def __init__(self):
        self.client = voyageai.Client(api_key=config.VOYAGE_API_KEY)
        self.model = config.VOYAGE_MODEL

    def __call__(self, input):
        result = self.client.embed(input, model=self.model, input_type="document")
        return result.embeddings


class ShabadVectorStore:
    def __init__(self):
        self.embedding_fn = VoyageEmbeddingFunction()
        self.client = chromadb.PersistentClient(path=config.CHROMA_DB_PATH)
        self.collection = self.client.get_or_create_collection(
            name="shabads",
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def add_shabads(self, shabads):
        """Add enriched shabads to the vector store."""
        ids = []
        documents = []
        metadatas = []

        for s in shabads:
            if s.get("enrichment_status") != "complete":
                continue

            ids.append(str(s["id"]))
            documents.append(self._build_embedding_text(s))
            metadatas.append({
                "title": s["title"],
                "keertani": s.get("keertani", ""),
                "sggs_raag": s.get("sggs_raag") or "",
                "performance_raag": s.get("performance_raag") or "",
                "ang": s.get("ang_number") or 0,
                "writer": s.get("writer") or "",
                "primary_theme": s.get("primary_theme") or "",
                "mood": s.get("mood") or "",
                "occasions": ",".join(s.get("occasions", [])),
                "confidence": s.get("confidence", "Medium"),
            })

        if not ids:
            print("No enriched shabads to add.")
            return

        # Upsert in batches respecting Voyage AI rate limits
        # Free tier without payment: 3 RPM, 10K TPM
        # ~200 tokens per shabad → 10 shabads ≈ 2K tokens (safe under 10K TPM)
        batch_size = 10
        total_batches = (len(ids) + batch_size - 1) // batch_size
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            batch_docs = documents[i:i + batch_size]
            batch_meta = metadatas[i:i + batch_size]
            batch_num = i // batch_size + 1
            print(f"  Embedding batch {batch_num}/{total_batches} ({len(batch_ids)} shabads)...", end=" ", flush=True)

            # Retry with exponential backoff for rate limits
            for attempt in range(5):
                try:
                    self.collection.upsert(
                        ids=batch_ids,
                        documents=batch_docs,
                        metadatas=batch_meta,
                    )
                    print("done")
                    break
                except Exception as e:
                    if "RateLimitError" in str(type(e).__name__) or "rate" in str(e).lower():
                        wait = 25 * (attempt + 1)
                        print(f"rate limited, waiting {wait}s...", end=" ", flush=True)
                        time.sleep(wait)
                    else:
                        raise

            if i + batch_size < len(ids):
                time.sleep(22)  # Stay within 3 RPM limit

        print(f"Total in vector store: {self.collection.count()}")

    def search_similar(self, query_text, n_results=20, exclude_ids=None, where_filter=None):
        """
        Search for semantically similar shabads.
        Returns list of dicts with id, title, score, metadata.
        """
        kwargs = {
            "query_texts": [query_text],
            "n_results": min(n_results + (len(exclude_ids) if exclude_ids else 0), self.collection.count()),
        }
        if where_filter:
            kwargs["where"] = where_filter

        results = self.collection.query(**kwargs)

        matches = []
        for i in range(len(results["ids"][0])):
            sid = results["ids"][0][i]
            if exclude_ids and sid in exclude_ids:
                continue
            matches.append({
                "id": int(sid),
                "distance": results["distances"][0][i] if results.get("distances") else None,
                "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                "document": results["documents"][0][i] if results.get("documents") else "",
            })

        return matches[:n_results]

    def _build_embedding_text(self, shabad):
        """Build composite text for embedding."""
        parts = [shabad["title"]]

        if shabad.get("english_translation"):
            parts.append(shabad["english_translation"][:500])
        if shabad.get("primary_theme"):
            parts.append(f"Theme: {shabad['primary_theme']}")
        if shabad.get("secondary_themes"):
            parts.append(f"Themes: {', '.join(shabad['secondary_themes'])}")
        if shabad.get("mood"):
            parts.append(f"Mood: {shabad['mood']}")
        if shabad.get("brief_meaning"):
            parts.append(shabad["brief_meaning"])

        return " | ".join(parts)

    def get_count(self):
        return self.collection.count()
