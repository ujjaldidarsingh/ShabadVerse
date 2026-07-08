"""ChromaDB vector store for semantic shabad search.

Embeddings use ChromaDB's built-in ONNX export of all-MiniLM-L6-v2
(ONNXMiniLM_L6_V2). This is the SAME model that the previous
SentenceTransformerEmbeddingFunction wrapped, minus the torch runtime —
it runs on onnxruntime (which ChromaDB already ships), so the Docker
image drops the multi-GB torch/CUDA stack while keeping identical 384-dim
vectors and live query embedding for semantic search.
"""

import chromadb
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
import config


class ShabadVectorStore:
    def __init__(self, collection_name=None):
        # ONNXMiniLM_L6_V2 is hardcoded to all-MiniLM-L6-v2; no model_name arg.
        # The ~90MB ONNX model is downloaded on first use and cached; the
        # Dockerfile pre-warms this cache at build time so runtime needs no network.
        self.embedding_fn = ONNXMiniLM_L6_V2()
        self.client = chromadb.PersistentClient(path=config.CHROMA_DB_PATH)
        self.collection_name = collection_name or config.PERSONAL_COLLECTION_NAME
        try:
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
        except ValueError as err:
            # A legacy collection persisted with a different embedding function
            # (pre-ONNX migration) raises an embedding-function conflict. Open it
            # as-is rather than crashing the app; collections that need ONNX
            # should be rebuilt via reset_collection() (the bootstrap re-embed).
            if "embedding function" not in str(err).lower():
                raise
            self.collection = self.client.get_collection(name=self.collection_name)

    def reset_collection(self):
        """Drop and recreate this collection with the ONNX embedding function.

        Required when migrating from the old SentenceTransformer-embedded
        collection: ChromaDB pins an embedding-function config to each
        collection, so a clean re-embed must start from a fresh collection.
        """
        try:
            self.client.delete_collection(self.collection_name)
        except (ValueError, chromadb.errors.NotFoundError):
            # Collection didn't exist yet — nothing to drop.
            pass
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
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

        # Local embeddings — no rate limits, use large batches
        batch_size = 200
        total_batches = (len(ids) + batch_size - 1) // batch_size
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i : i + batch_size]
            batch_docs = documents[i : i + batch_size]
            batch_meta = metadatas[i : i + batch_size]
            batch_num = i // batch_size + 1
            print(
                f"  Embedding batch {batch_num}/{total_batches} ({len(batch_ids)} shabads)...",
                end=" ",
                flush=True,
            )
            self.collection.upsert(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_meta,
            )
            print("done")

        print(f"Total in vector store: {self.collection.count()}")

    def add_sggs_shabads(self, shabads):
        """Add SGGS shabads (from BaniDB) to the vector store."""
        ids = []
        documents = []
        metadatas = []

        for s in shabads:
            ids.append(str(s["banidb_shabad_id"]))
            documents.append(self._build_sggs_embedding_text(s))
            metadatas.append({
                "title": s.get("transliteration", "")[:100],
                "sggs_raag": s.get("sggs_raag") or "",
                "ang": s.get("ang_number") or 0,
                "writer": s.get("writer") or "",
                "primary_theme": s.get("primary_theme") or "",
                "mood": s.get("mood") or "",
                "brief_meaning": s.get("brief_meaning") or "",
                "rahao_english": s.get("rahao_english") or "",
            })

        if not ids:
            print("No SGGS shabads to add.")
            return

        batch_size = 200
        total_batches = (len(ids) + batch_size - 1) // batch_size
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i : i + batch_size]
            batch_docs = documents[i : i + batch_size]
            batch_meta = metadatas[i : i + batch_size]
            batch_num = i // batch_size + 1
            print(
                f"  Embedding batch {batch_num}/{total_batches} ({len(batch_ids)} shabads)...",
                end=" ",
                flush=True,
            )
            self.collection.upsert(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_meta,
            )
            print("done")

        print(f"Total in vector store: {self.collection.count()}")

    def add_lines(self, lines):
        """Add individual verses (tuks) to the vector store.

        Each line is embedded on its English translation alone — the line IS the
        unit of meaning here, so no shabad-level theme text is mixed in (that
        would drag every line of a shabad toward the same point in vector space
        and defeat line-level matching).

        Expects dicts with: id, english, gurmukhi, shabad_id, line_index,
        is_rahao, ang.
        """
        if not lines:
            print("No lines to add.")
            return

        batch_size = 500
        total_batches = (len(lines) + batch_size - 1) // batch_size
        for i in range(0, len(lines), batch_size):
            batch = lines[i : i + batch_size]
            batch_num = i // batch_size + 1
            print(
                f"  Embedding batch {batch_num}/{total_batches} ({len(batch)} lines)...",
                end=" ",
                flush=True,
            )
            self.collection.upsert(
                ids=[ln["id"] for ln in batch],
                documents=[ln["english"] for ln in batch],
                metadatas=[
                    {
                        "shabad_id": ln["shabad_id"],
                        "line_index": ln["line_index"],
                        "gurmukhi": ln["gurmukhi"],
                        "english": ln["english"],
                        "is_rahao": ln["is_rahao"],
                        "ang": ln["ang"],
                    }
                    for ln in batch
                ],
            )
            print("done")

        print(f"Total lines in vector store: {self.collection.count()}")

    def search_similar(self, query_text, n_results=20, exclude_ids=None, where_filter=None):
        """
        Search for semantically similar shabads.
        Returns list of dicts with id, title, score, metadata.
        """
        count = self.collection.count()
        if count == 0:
            return []

        kwargs = {
            "query_texts": [query_text],
            "n_results": min(n_results + (len(exclude_ids) if exclude_ids else 0), count),
        }
        if where_filter:
            kwargs["where"] = where_filter

        results = self.collection.query(**kwargs)

        matches = []
        for i in range(len(results["ids"][0])):
            sid = results["ids"][0][i]
            if exclude_ids and sid in exclude_ids:
                continue
            # Try to return int id for personal library lookups
            try:
                parsed_id = int(sid)
            except (ValueError, TypeError):
                parsed_id = sid
            matches.append({
                "id": parsed_id,
                "distance": results["distances"][0][i] if results.get("distances") else None,
                "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                "document": results["documents"][0][i] if results.get("documents") else "",
            })

        return matches[:n_results]

    def _build_embedding_text(self, shabad):
        """Build composite text for embedding (personal library shabads)."""
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

    def _build_sggs_embedding_text(self, shabad):
        """Build composite text for embedding (SGGS shabads from BaniDB).

        Prioritizes theme/mood/meaning over transliteration to avoid
        false clustering by raag/writer. Translation is included for
        shabads without enriched themes.
        """
        parts = []

        # Theme data first (most important for matching)
        if shabad.get("primary_theme"):
            parts.append(f"Theme: {shabad['primary_theme']}")
        if shabad.get("mood"):
            parts.append(f"Mood: {shabad['mood']}")
        if shabad.get("brief_meaning"):
            parts.append(shabad["brief_meaning"])

        # Rahao line is the core mukhra - highly relevant
        if shabad.get("rahao_english"):
            parts.append(f"Core verse: {shabad['rahao_english']}")

        # Translation as fallback (but not transliteration - it causes raag/writer clustering)
        if shabad.get("english_translation"):
            parts.append(shabad["english_translation"][:400])

        # Deliberately omit: transliteration, raag, writer
        # These cause "Aasaa Mahalla 5" to match other "Aasaa Mahalla 5" instead of thematic matches

        return " | ".join(parts) if parts else "Unknown shabad"

    def get_count(self):
        return self.collection.count()
