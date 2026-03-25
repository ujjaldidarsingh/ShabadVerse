"""Parkaran Helper - Flask Application."""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template
from api.routes import api_bp
from api.graph_api import graph_bp

app = Flask(__name__)
app.register_blueprint(api_bp, url_prefix="/api")
app.register_blueprint(graph_bp, url_prefix="/api")


@app.route("/")
@app.route("/explore")
def explore():
    return render_template("explore.html")


@app.route("/database")
def database():
    return render_template("database.html")


@app.route("/discover")
def discover():
    return render_template("discover.html")


@app.route("/builder")
@app.route("/builder-classic")
def builder():
    return render_template("builder.html")


@app.route("/reviewer")
def reviewer():
    return render_template("reviewer.html")


@app.route("/occasions")
def occasions():
    return render_template("occasions.html")


def _startup_checks():
    """Print startup diagnostics."""
    import config
    from database.vector_store import ShabadVectorStore

    print("\n--- Startup Checks ---")

    # Check personal library
    try:
        store = ShabadVectorStore()
        count = store.get_count()
        print(f"  Personal library: {count} shabads in vector store")
        if count == 0:
            print("  Warning: No personal shabads embedded. Run: python bootstrap/setup.py")
    except Exception as e:
        print(f"  Warning: Could not check personal library: {e}")

    # Check SGGS collection
    try:
        sggs_store = ShabadVectorStore(collection_name=config.SGGS_COLLECTION_NAME)
        sggs_count = sggs_store.get_count()
        print(f"  SGGS collection: {sggs_count} shabads in vector store")
        if sggs_count == 0:
            print("  Warning: No SGGS shabads embedded. Run: python bootstrap/setup.py")
    except Exception as e:
        print(f"  Warning: Could not check SGGS collection: {e}")

    # Check Ollama
    try:
        from llm.ollama_client import OllamaClient

        llm = OllamaClient()
        if llm.is_available():
            print(f"  Ollama: available (model: {config.OLLAMA_MODEL})")
        else:
            print(f"  Ollama: model '{config.OLLAMA_MODEL}' not found (LLM features disabled)")
    except Exception:
        print("  Ollama: not running (LLM features disabled)")

    print("----------------------\n")


if __name__ == "__main__":
    _startup_checks()
    app.run(debug=True, port=5050)
