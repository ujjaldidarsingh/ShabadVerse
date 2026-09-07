"""ShabadVerse - SGGS Graph Explorer & Parkaran Builder."""

import sys
import os
import gzip
import sqlite3
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, redirect, render_template, url_for, request, jsonify
from api.graph_api import graph_bp
import api.topics  # Register topic routes before the blueprint is attached.

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 256 * 1024
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
    if response.mimetype == 'application/json' and response.status_code == 200:
        response.vary.add('Accept-Encoding')
        if request.accept_encodings['gzip'] > 0 and len(response.get_data()) > 1024:
            response.set_data(gzip.compress(response.get_data(), compresslevel=6))
            response.headers['Content-Encoding'] = 'gzip'
    return response


@lru_cache(maxsize=1)
def checked_release():
    import config
    from release import verify
    directory = Path(config.DATA_DIR)
    if (directory / 'BUILD_INCOMPLETE').exists():
        raise ValueError('Dataset build is incomplete')
    return verify(directory)


@app.route('/health/ready')
def readiness():
    try:
        manifest = checked_release()
        return jsonify({'ready': True, 'dataset_id': manifest['dataset_id'], 'counts': manifest['counts']})
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        app.logger.error('Dataset readiness: %s', error)
        return jsonify({'ready': False, 'error': 'Dataset validation failed'}), 503


@app.route('/api/release')
def release_identity():
    try:
        manifest = checked_release()
        return jsonify({key: manifest[key] for key in ('dataset_id', 'code_commit', 'code_sha256', 'counts', 'cultural_review', 'publish_approval')})
    except (OSError, ValueError, KeyError, sqlite3.Error):
        return jsonify({'error': 'No verified release manifest'}), 503


@app.errorhandler(RuntimeError)
def unavailable(error):
    app.logger.error("Local service unavailable: %s", error)
    return jsonify({"error": "Local data or search model unavailable"}), 503


@app.route("/")
def app_shell():
    """Unified single-page app with Explore and Review tabs."""
    return render_template("app.html")


@app.route("/about")
def about():
    """Public explainer: what ShabadVerse is, how to use it, and how the
    tag taxonomy and connections are built (AI transparency)."""
    from api.graph_api import _get_graph, _get_tag_vocab
    from database.corpus import shabad
    graph = _get_graph()
    neighbors = [{"id": n['id'], **graph['metadata'][n['id']]} for n in graph['neighbors'].get('970', [])[:3]]
    return render_template("about.html", demo=shabad('970'), demo_neighbors=neighbors,
                           concept_count=len(_get_tag_vocab().get('theme_tags', {})))


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
            print("  Warning: No SGGS shabads embedded. Restore a complete dataset snapshot; see architecture.md")
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
