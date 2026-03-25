# Parkaran Tool Current State

## Status: Active Development

## Recent Changes
- Initial commit with full Flask app, enrichment pipeline, and vector store

## Active Features
- All 5 core features operational: Database, Discover, Builder, Reviewer, Occasions
- ~60-70 shabads fully enriched and queryable in ChromaDB
- BaniDB integration live with SQLite caching (157 MB cache)
- Claude-powered theme extraction, re-ranking, and flow analysis working

## Environment
- **Run**: `cd parkaran-helper && flask run` (port 5000)
- **Dependencies**: `pip install -r parkaran-helper/requirements.txt`
- **API Keys**: Set in `parkaran-helper/.env` (ANTHROPIC_API_KEY, VOYAGE_API_KEY)
- **Data**: enriched_shabads.json (5.1 MB), shabad_cache.db (157 MB), chroma_db/

## Known Issues
- Voyage AI free tier rate limits (3 RPM) require 22s delays between embedding batches
- No ML-based sentiment — Claude does all semantic analysis
- Frontend uses CDN for Tailwind (requires internet)
- Large PDF references (1.5GB+) in repo root
