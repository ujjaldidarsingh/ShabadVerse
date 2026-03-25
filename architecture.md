# Parkaran Tool Architecture

## System Overview
Flask web app for Sikh keertan parkaran (set-list) management. Enriches user's shabad database from Excel via BaniDB matching + Claude theme extraction, stores as Voyage AI embeddings in ChromaDB, then enables semantic search, AI-powered parkaran building, flow review, and occasion-based suggestions.

## Entry Point

| Command | Purpose |
|---|---|
| `cd parkaran-helper && flask run` | Flask dev server (port 5000) |
| `python parkaran-helper/app.py` | Direct run |

## Directory Map

```
Parkaran Tool/
├── Keertan Track Database.xlsx              # Source data (~100 shabads)
├── Keertan and Music [compiled].xlsx        # Alternative source
├── PDF References/                          # SGGS translations (5 PDFs, 1.5GB+)
└── parkaran-helper/                         # Flask application
    ├── app.py                               # Entry point (5 page routes + API blueprint)
    ├── config.py                            # API keys, model names, file paths
    ├── requirements.txt                     # flask, anthropic, voyageai, chromadb, python-dotenv
    ├── .env                                 # API keys (ANTHROPIC_API_KEY, VOYAGE_API_KEY)
    ├── api/
    │   ├── routes.py                        # 9 REST endpoints (62KB)
    │   ├── parkaran_builder.py              # Seed shabads → vector search → Claude re-rank
    │   ├── parkaran_reviewer.py             # Flow analysis for complete parkarans
    │   └── occasion_suggester.py            # 10 Sikh occasions → themed suggestions
    ├── database/
    │   └── vector_store.py                  # ChromaDB + Voyage AI embedding function
    ├── enrichment/                          # Data pipeline (Excel → enriched JSON)
    │   ├── data_loader.py                   # Load/save Excel & enriched JSON
    │   ├── banidb_matcher.py                # BaniDB API fuzzy matching
    │   ├── claude_enricher.py               # Claude theme extraction (batches of 12)
    │   ├── enrich_pipeline.py               # Master orchestration (2 phases)
    │   └── embedding_generator.py           # Generate ChromaDB vectors
    ├── templates/                           # Jinja2 HTML pages
    │   ├── base.html                        # Layout
    │   ├── index.html                       # Home (5 feature cards)
    │   ├── database.html                    # Browse personal shabads
    │   ├── discover.html                    # Search full SGGS via BaniDB
    │   ├── builder.html                     # Parkaran creation
    │   ├── reviewer.html                    # Flow analysis
    │   └── occasions.html                   # Occasion lookup
    ├── static/
    │   ├── css/style.css                    # Tailwind + custom Sikh-themed (navy/gold)
    │   └── js/
    │       ├── app.js                       # Global setup
    │       ├── database-view.js             # Database page logic
    │       ├── discover.js                  # Discover page logic
    │       ├── parkaran-builder.js          # Builder interactions
    │       └── parkaran-reviewer.js         # Reviewer interactions
    └── data/
        ├── enriched_shabads.json            # Fully enriched dataset (5.1 MB)
        ├── shabad_cache.db                  # SQLite cache (157 MB)
        └── chroma_db/                       # Persistent ChromaDB vector index
```

## API Endpoints (api/routes.py)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/shabads` | List shabads with filters (q, keertani, raag, confidence) |
| GET | `/api/shabads/<id>` | Full shabad details |
| GET | `/api/keertanis` | List all keertani names |
| GET | `/api/raags` | List all raags |
| GET | `/api/discover/search` | BaniDB SGGS search (first-letter or full-text) |
| GET | `/api/discover/shabad/<banidb_id>` | Full BaniDB shabad details |
| POST | `/api/discover/enrich` | On-the-fly Claude theme extraction |
| POST | `/api/parkaran/build` | Seed IDs → vector search + Claude re-ranking |
| POST | `/api/parkaran/review` | Analyze thematic flow of complete parkaran |
| GET | `/api/occasions` | List 10 Sikh occasions |
| GET | `/api/occasions/<id>/suggest` | Themed shabads for occasion |

## Data Pipeline

```
Excel (Keertan Track Database.xlsx)
  → Phase 1: BaniDB Matching (banidb_matcher.py)
    → Fuzzy match title → extract ang, raag, writer, translations, banidb_id
    → Cache in SQLite (shabad_cache.db)
  → Phase 2: Claude Theme Extraction (claude_enricher.py)
    → Batch of 12 → primary_theme, secondary_themes, mood, occasions, brief_meaning
    → Model: claude-sonnet-4-20250514
  → Save to enriched_shabads.json
  → Phase 3: Embedding Generation (embedding_generator.py)
    → Voyage AI (voyage-3-5-lite) embeddings
    → Composite text: title + translation[:500] + theme + mood + meaning
    → ChromaDB upsert (cosine HNSW)
```

## External Dependencies

| Service | Usage | Rate Limits |
|---|---|---|
| **Anthropic Claude API** | Theme extraction, parkaran re-ranking, flow review | Standard API limits |
| **Voyage AI** | Semantic embeddings (voyage-3-5-lite) | Free: 3 RPM, 10K TPM → 22s batch delays |
| **BaniDB v2 API** | SGGS search + shabad data (`api.banidb.com/v2`) | 0.5s per search, 0.3s per detail |

## Tech Stack
- Python 3, Flask 3.1, Anthropic SDK, Voyage AI SDK, ChromaDB >=1.0
- Frontend: Tailwind CSS (CDN), vanilla JS, Jinja2 templates
- Storage: ChromaDB (vectors), SQLite (cache), JSON (enriched data)
- Model: claude-sonnet-4-20250514

## Key Design Patterns
- Lazy loading: Builder/Reviewer/Suggester initialized on first API call
- Triple-layer caching: SQLite (BaniDB), JSON (enriched), ChromaDB (vectors)
- Graceful degradation: Claude failures fall back to vector similarity results
- Batch processing: Claude (12/batch), Voyage AI (10/batch with exponential backoff)
