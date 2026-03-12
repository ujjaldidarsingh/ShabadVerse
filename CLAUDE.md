# Parkaran Tool

Sikh keertan (devotional music) management app for building, discovering, and reviewing parkaran (keertan sets). Combines a personal shabad database with BaniDB search, AI-powered theme extraction, and vector similarity matching.

## Stack
- **Backend**: Python, Flask 3.1, Anthropic SDK, Voyage AI (embeddings), ChromaDB (vector store)
- **Frontend**: HTML templates (Jinja2), served by Flask
- **APIs**: BaniDB v2 (`api.banidb.com`), Anthropic Claude, Voyage AI
- **Data**: JSON enriched shabads, SQLite cache, ChromaDB vector DB, Excel keertan database
- **Port**: 5050 (debug mode)

## Structure
- **`parkaran-helper/`**: Main Flask application
  - `app.py` - Flask entry point, routes to pages
  - `config.py` - API keys (from `.env`), BaniDB settings, file paths
  - `api/routes.py` - REST API endpoints (shabads, discover, builder, reviewer, occasions)
  - `api/parkaran_builder.py` - AI-assisted parkaran set builder (vector similarity)
  - `api/parkaran_reviewer.py` - Review/score a parkaran set
  - `api/occasion_suggester.py` - Suggest shabads for specific occasions
  - `enrichment/` - Data pipeline: load, match BaniDB, Claude theme extraction, embeddings
  - `database/vector_store.py` - ChromaDB vector store operations
  - `templates/` - HTML pages (index, database, discover, builder, reviewer, occasions)
  - `static/` - CSS/JS assets
  - `data/` - enriched_shabads.json, chroma_db/, shabad_cache.db
- **Root**: Sikh scripture PDFs (SGGS translations, Guru Granth Darpan), keertan track databases (.xlsx, .pages)

## Commands
```bash
cd parkaran-helper
pip install -r requirements.txt
python app.py                    # Runs on http://localhost:5050
```

## Environment Variables (`.env`)
- `ANTHROPIC_API_KEY` - For Claude theme extraction
- `VOYAGE_API_KEY` - For embedding generation

## Key Features
- **Database**: Browse/search personal shabad collection with filters (keertani, raag, theme, mood)
- **Discover**: Search BaniDB (SGGS) by first-letter or full-text, cross-reference with personal DB
- **Builder**: Given seed shabads, find similar ones via vector embeddings for parkaran construction
- **Reviewer**: Score a parkaran set for thematic coherence and flow
- **Occasions**: Suggest shabads appropriate for specific Sikh occasions
- **Enrichment Pipeline**: Batch-enrich shabads with Claude (themes, mood) and Voyage (embeddings)
