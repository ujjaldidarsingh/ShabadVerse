"""ShabadVerse - SGGS Graph Explorer & Parkaran Builder."""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, redirect, render_template, url_for
from api.graph_api import graph_bp

app = Flask(__name__)
app.register_blueprint(graph_bp, url_prefix="/api")

# Only register personal library API routes in development
if os.getenv("FLASK_ENV") == "development":
    from api.routes import api_bp

    app.register_blueprint(api_bp, url_prefix="/api")


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.route("/")
def app_shell():
    """Unified single-page app with Explore and Review tabs."""
    return render_template("app.html")


@app.route("/explore")
def explore_redirect():
    """Legacy route — redirect to the unified app with Explore tab active."""
    return redirect(url_for("app_shell") + "?tab=explore", code=301)


@app.route("/reviewer")
def reviewer_redirect():
    """Legacy route — redirect to the unified app with Review tab active."""
    return redirect(url_for("app_shell") + "?tab=review", code=301)


def _startup_checks():
    """Print startup diagnostics."""
    import config
    from database.vector_store import ShabadVectorStore

    print("\n--- ShabadVerse Startup ---")

    # Check SGGS collection (primary data source)
    try:
        sggs_store = ShabadVectorStore(collection_name=config.SGGS_COLLECTION_NAME)
        sggs_count = sggs_store.get_count()
        print(f"  SGGS collection: {sggs_count} shabads")
        if sggs_count == 0:
            print("  Warning: No SGGS shabads embedded. Run: python bootstrap/setup.py")
    except Exception as e:
        print(f"  Warning: Could not check SGGS collection: {e}")

    # Check Ollama (optional)
    try:
        from llm.ollama_client import OllamaClient

        llm = OllamaClient()
        if llm.is_available():
            print(f"  Ollama: available (model: {config.OLLAMA_MODEL})")
        else:
            print(f"  Ollama: not available (LLM features disabled)")
    except Exception:
        print("  Ollama: not running (LLM features disabled)")

    env = os.getenv("FLASK_ENV", "production")
    print(f"  Mode: {env}")
    print("---------------------------\n")


if __name__ == "__main__":
    _startup_checks()
    is_dev = os.getenv("FLASK_ENV") == "development"
    app.run(debug=is_dev, port=5050)
