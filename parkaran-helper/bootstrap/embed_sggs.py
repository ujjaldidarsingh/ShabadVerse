"""Embed all SGGS shabads into ChromaDB for semantic search."""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from database.vector_store import ShabadVectorStore


def embed_sggs():
    """Load SGGS shabads and embed into ChromaDB."""
    sggs_path = config.SGGS_DATA_PATH

    if not os.path.exists(sggs_path):
        print(f"SGGS data not found at {sggs_path}")
        print("Run 'python bootstrap/fetch_sggs.py' first.")
        return

    print("Loading SGGS shabads...")
    with open(sggs_path, encoding="utf-8") as f:
        shabads = json.load(f)

    # Filter out shabads without translations (can't embed meaningfully)
    valid = [s for s in shabads if s.get("english_translation") or s.get("transliteration")]
    print(f"Loaded {len(shabads)} shabads, {len(valid)} have text for embedding.")

    print(f"Initializing SGGS vector store (collection: {config.SGGS_COLLECTION_NAME})...")
    store = ShabadVectorStore(collection_name=config.SGGS_COLLECTION_NAME)

    print("Generating embeddings and storing...")
    store.add_sggs_shabads(valid)

    print(f"\nDone! {store.get_count()} SGGS shabads in vector store.")


if __name__ == "__main__":
    embed_sggs()
