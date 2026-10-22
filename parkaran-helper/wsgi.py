"""WSGI entry point for production deployment."""

import threading

from app import app
from api import meaning_search

# Build the search index while the first visitor is still loading the page.
threading.Thread(target=meaning_search.warm, name="search-warm-up", daemon=True).start()

if __name__ == "__main__":
    app.run()
