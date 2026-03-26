# Parkaran Tool Architecture

## System Overview
Flask web app for Sikh keertan parkaran (set-list) exploration and building. Runs fully local: sentence-transformers for embeddings, Ollama for LLM features, ChromaDB for vector search, precomputed similarity graph for instant tag-based suggestions. Primary UI is an interactive graph explorer (Cytoscape.js) showing thematic connections across all 5,542 SGGS shabads.

## Entry Point

| Command | Purpose |
|---|---|
| `cd parkaran-helper && python app.py` | Flask dev server (port 5050) |
| `python bootstrap/setup.py` | One-time setup: embeddings + SGGS fetch + graph build |

## Directory Map

```
Parkaran Tool/
├── CLAUDE.md, state.md, architecture.md, DESIGN.md
├── Keertan Track Database.xlsx        # Personal repertoire source (~1,080 shabads)
└── parkaran-helper/                   # Flask application
    ├── app.py                         # Entry point (explore, reviewer, builder, etc.)
    ├── config.py                      # Ollama URL, embedding model, collection names, paths
    ├── requirements.txt               # flask, chromadb, sentence-transformers, ollama, requests
    ├── api/
    │   ├── routes.py                  # Personal library + BaniDB endpoints
    │   ├── graph_api.py               # Graph explorer endpoints (neighbors, tags, verses)
    │   ├── parkaran_builder.py        # Graph-first + vector fallback builder
    │   ├── parkaran_reviewer.py       # Parkaran flow review (Ollama-powered)
    │   └── occasion_suggester.py      # 10 Sikh occasions → themed suggestions
    ├── llm/
    │   └── ollama_client.py           # Ollama wrapper (generate, generate_json, is_available)
    ├── database/
    │   └── vector_store.py            # ChromaDB + SentenceTransformerEmbeddingFunction
    ├── enrichment/                    # Data pipeline (Excel → enriched JSON)
    │   ├── data_loader.py             # Load/save Excel & enriched JSON
    │   ├── banidb_matcher.py          # BaniDB API + SQLite cache + fuzzy matching
    │   ├── claude_enricher.py         # Theme extraction (now uses Ollama, name kept for compat)
    │   ├── enrich_pipeline.py         # Master orchestration (2 phases)
    │   └── embedding_generator.py     # Generate ChromaDB vectors
    ├── bootstrap/                     # One-time data preparation scripts
    │   ├── setup.py                   # Master setup (check deps, fetch SGGS, embed, build graph)
    │   ├── fetch_sggs.py              # Fetch all 5,542 SGGS shabads from BaniDB (ang-by-ang)
    │   ├── embed_sggs.py              # Embed SGGS into ChromaDB collection
    │   ├── add_rahao.py               # Extract rahao pada + fix display names
    │   ├── enrich_sggs.py             # Batch theme/mood extraction via Ollama
    │   ├── build_taxonomy.py          # Build tag vocabulary (Opus + Qwen clustering)
    │   ├── tag_shabads.py             # Assign taxonomy tags to all shabads
    │   ├── validate_tags.py           # Dual-model tag validation (Qwen + DeepSeek R1)
    │   └── build_graph.py             # Precompute similarity graph (Jaccard + embedding cosine)
    ├── templates/                     # Jinja2 HTML pages
    │   ├── base.html                  # Layout (Tailwind CDN, fonts, nav)
    │   ├── explore.html               # Graph explorer (primary UI)
    │   ├── reviewer.html              # Parkaran flow review
    │   ├── builder.html               # Classic seed-based builder
    │   ├── database.html, discover.html, occasions.html
    │   └── index.html                 # Redirects to /explore
    ├── static/
    │   ├── css/style.css              # Celestial Observatory design system
    │   └── js/
    │       ├── graph-explorer.js      # Cytoscape.js graph: radial layout, tooltips, forces
    │       ├── parkaran-reviewer.js   # Reviewer: flow list, detail panel, transitions
    │       ├── parkaran-builder.js    # Classic builder interactions
    │       ├── app.js, database-view.js, discover.js
    └── data/
        ├── sggs_all_shabads.json      # 5,542 SGGS shabads (enriched, tagged, rahao)
        ├── enriched_shabads.json      # 1,035 personal library shabads
        ├── similarity_graph.json      # Precomputed graph (7.4 MB)
        ├── tag_vocabulary.json        # 372 theme/mood tags
        ├── shabad_cache.db            # SQLite BaniDB cache
        └── chroma_db/                 # Persistent vector index (personal + SGGS collections)
```

## Graph Explorer API (api/graph_api.py)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/graph/init` | Metadata + tag_index + tag_vocab for client-side rendering |
| GET | `/api/graph/neighbors/<id>` | Neighbors grouped by tag (threshold, per_tag, tuk_english params) |
| GET | `/api/graph/shabad/<id>/verses` | Verse-level data with rahao detection |
| POST | `/api/graph/shabads` | Batch shabad details by BaniDB IDs (for reviewer) |
| GET | `/api/tags` | All tags with counts and descriptions |
| GET | `/api/tags/<tag>/shabads` | Shabads for a given tag |

## Bootstrap Pipeline

```
1. fetch_sggs.py     → Iterate BaniDB angs 1-1430 → sggs_all_shabads.json (5,542 shabads)
2. add_rahao.py      → Extract rahao pada + fix title-like display names
3. enrich_sggs.py    → Ollama theme/mood/meaning extraction (batch of 5)
4. embed_sggs.py     → sentence-transformers → ChromaDB "sggs_shabads" collection
5. build_taxonomy.py → Cluster 3,108 raw themes into 372 canonical tags
6. tag_shabads.py    → Assign tags via alias lookup (99%) + Ollama fallback (1%)
7. validate_tags.py  → Dual-model validation (Qwen + DeepSeek R1)
8. build_graph.py    → Jaccard (50%) + embedding cosine (50%), core/branch pool split, K=40
```

## Similarity Graph Scoring
- **Tag overlap**: Jaccard similarity between shabad tag sets (50% weight)
- **Embedding cosine**: sentence-transformers all-MiniLM-L6-v2, 384-dim (50% weight)
- **Diversity**: Core pool (shares all tags, max 4/tag) + Branch pool (shares 1 tag, brings new ones, max 4/tag)
- **API grouping**: Core neighbors under shared tags; branching neighbors under the NEW tag they bring

## External Dependencies

| Service | Usage | Notes |
|---|---|---|
| **Ollama** (local) | Theme extraction, re-ranking, review | qwen3:14b primary, deepseek-r1:14b validation |
| **BaniDB v2** | SGGS search + shabad data | One-time fetch, cached in SQLite |
| **HuggingFace** | Model download (all-MiniLM-L6-v2) | One-time, ~80MB |

## Tech Stack
- Python 3.13, Flask 3.1, Ollama, sentence-transformers, ChromaDB >=1.0
- Frontend: Tailwind CSS (CDN), Cytoscape.js, vanilla JS, Jinja2, Noto Serif Gurmukhi
- Storage: ChromaDB (vectors), SQLite (BaniDB cache), JSON (enriched data, graph, taxonomy)
