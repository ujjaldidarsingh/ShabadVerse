"""Master setup script for Parkaran Tool.

Checks prerequisites, fetches SGGS data, and builds all embeddings.
Run this once after installation to prepare the app for offline use.
"""

import sys
import os
import subprocess
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


def check_ollama():
    """Check if Ollama is installed and running."""
    print("Checking Ollama...")
    try:
        import ollama

        client = ollama.Client(host=config.OLLAMA_BASE_URL)
        models = client.list()
        model_names = [m.model for m in models.models]
        print(f"  Ollama is running. Available models: {', '.join(model_names) or 'none'}")

        # Check if our model is available
        if not any(config.OLLAMA_MODEL in name for name in model_names):
            print(f"  Model '{config.OLLAMA_MODEL}' not found. Pulling...")
            subprocess.run(["ollama", "pull", config.OLLAMA_MODEL], check=True)
            print(f"  Model '{config.OLLAMA_MODEL}' pulled successfully.")
        else:
            print(f"  Model '{config.OLLAMA_MODEL}' is available.")
        return True
    except Exception as e:
        print(f"  Warning: Ollama not available ({e})")
        print("  The app will work without Ollama but LLM features (re-ranking, review) will be disabled.")
        print("  Install Ollama from https://ollama.ai and run: ollama pull " + config.OLLAMA_MODEL)
        return False


def check_embedding_model():
    """Check if the embedding model is available (downloads on first use)."""
    print(f"\nChecking embedding model ({config.EMBEDDING_MODEL})...")
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(config.EMBEDDING_MODEL)
        # Quick test
        model.encode(["test"])
        print(f"  Embedding model '{config.EMBEDDING_MODEL}' is ready.")
        return True
    except Exception as e:
        print(f"  Error loading embedding model: {e}")
        print("  Run: pip install sentence-transformers")
        return False


def rebuild_personal_embeddings():
    """Rebuild personal library embeddings with new model."""
    print("\nRebuilding personal library embeddings...")
    from enrichment.data_loader import load_enriched
    from database.vector_store import ShabadVectorStore

    shabads, _ = load_enriched()
    enriched = [s for s in shabads if s.get("enrichment_status") == "complete"]
    print(f"  Found {len(enriched)} enriched shabads.")

    if not enriched:
        print("  No enriched shabads found. Skipping.")
        return

    store = ShabadVectorStore()
    store.add_shabads(enriched)
    print(f"  Personal library: {store.get_count()} shabads embedded.")


def fetch_and_embed_sggs():
    """Fetch all SGGS data and embed it."""
    from bootstrap.fetch_sggs import fetch_all_sggs
    from bootstrap.embed_sggs import embed_sggs

    sggs_path = config.SGGS_DATA_PATH
    if os.path.exists(sggs_path):
        print(f"\nSGGS data already exists at {sggs_path}.")
        print("  Skipping fetch. Delete the file to re-fetch.")
    else:
        print("\nFetching all SGGS shabads from BaniDB...")
        fetch_all_sggs()

    print("\nEmbedding SGGS shabads...")
    embed_sggs()


def main():
    print("=" * 60)
    print("  Parkaran Tool Setup")
    print("=" * 60)
    print()

    # 1. Check embedding model
    if not check_embedding_model():
        print("\nSetup cannot continue without the embedding model.")
        sys.exit(1)

    # 2. Check Ollama (optional)
    check_ollama()

    # 3. Delete old ChromaDB if exists (might have incompatible dimensions)
    chroma_path = config.CHROMA_DB_PATH
    if os.path.exists(chroma_path):
        print(f"\nRemoving old ChromaDB at {chroma_path} (rebuilding with new model)...")
        shutil.rmtree(chroma_path)

    # 4. Rebuild personal library embeddings
    rebuild_personal_embeddings()

    # 5. Fetch and embed SGGS
    fetch_and_embed_sggs()

    print("\n" + "=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print(f"\nRun the app:  python app.py")
    print(f"Open: http://localhost:5050")


if __name__ == "__main__":
    main()
