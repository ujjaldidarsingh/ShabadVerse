"""ChromaDB vector store for semantic shabad search."""

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
import config


class ShabadVectorStore:
    def __init__(self, collection_name=None):
        self.embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name=config.EMBEDDING_MODEL
        )
        self.client = chromadb.PersistentClient(path=config.CHROMA_DB_PATH)
        self.collection = self.client.get_or_create_collection(
            name=collection_name or config.PERSONAL_COLLECTION_NAME,
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
