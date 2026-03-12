"""Generate embeddings and store in ChromaDB."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from enrichment.data_loader import load_enriched
from database.vector_store import ShabadVectorStore


def generate_embeddings():
    """Load enriched data and store embeddings in ChromaDB."""
    print("Loading enriched shabads...")
    shabads, _ = load_enriched()

    enriched = [s for s in shabads if s.get("enrichment_status") == "complete"]
    print(f"Enriched shabads: {len(enriched)}/{len(shabads)}")

    if not enriched:
        print("No enriched shabads found. Run the enrichment pipeline first.")
        return

    print("Initializing vector store...")
    store = ShabadVectorStore()

    print("Generating embeddings and storing...")
    store.add_shabads(enriched)

    print(f"\nDone! {store.get_count()} shabads in vector store.")


if __name__ == "__main__":
    generate_embeddings()
