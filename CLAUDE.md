# Parkaran Tool

Interactive graph explorer for Sri Guru Granth Sahib Ji. Maps thematic connections across all 5,542 SGGS shabads using a 372-tag taxonomy, precomputed similarity graph, and radial tag-clustered visualization. Runs fully local; no API keys needed.

## Quick Start
Read `architecture.md` and `state.md` before making changes.

```bash
cd parkaran-helper
pip install -r requirements.txt
python app.py                    # http://localhost:5050
```

First-time setup (one-time, ~20 min):
```bash
python bootstrap/setup.py       # Fetch SGGS, embed, build graph
python bootstrap/enrich_sggs.py # Theme extraction via Ollama (hours)
python bootstrap/build_taxonomy.py && python bootstrap/tag_shabads.py
python bootstrap/build_graph.py # Precompute similarity graph
```

## Stack
- **Backend**: Python 3.13, Flask 3.1, ChromaDB, sentence-transformers (all-MiniLM-L6-v2)
- **LLM**: Ollama (qwen3:14b) — optional, for theme extraction and explanations
- **Frontend**: Cytoscape.js (graph), Tailwind CSS (CDN), vanilla JS, Jinja2, Noto Serif Gurmukhi
- **Data**: BaniDB v2 (one-time fetch), ChromaDB vectors, precomputed similarity graph (JSON)
- **Port**: 5050

## Key Files
- `app.py` — Flask entry, routes (/ = explore, /reviewer, /builder, /database, /discover, /occasions)
- `api/graph_api.py` — Graph explorer API (neighbors, tags, verses, shabad batch)
- `api/routes.py` — Personal library + BaniDB endpoints
- `api/parkaran_builder.py` — Graph-first suggestions with vector fallback
- `bootstrap/build_graph.py` — Similarity graph: 50% Jaccard + 50% embedding cosine, core/branch pools
- `database/vector_store.py` — ChromaDB wrapper, SentenceTransformerEmbeddingFunction
- `llm/ollama_client.py` — Ollama wrapper (chat API, think=False for Qwen 3)
- `static/js/graph-explorer.js` — Cytoscape radial layout, tooltips, forces, parkaran trail
- `static/css/style.css` — Celestial Observatory design system
- `data/similarity_graph.json` — Precomputed graph (5,542 nodes, avg 12.9 neighbors)
- `data/sggs_all_shabads.json` — All SGGS shabads with themes, tags, rahao, summaries

## Environment
- **Python**: miniforge (`/opt/homebrew/Caskroom/miniforge/base/bin/python3`)
- **Ollama**: `brew install ollama && ollama pull qwen3:14b`
- No `.env` needed — app works without API keys (LLM features degrade gracefully)

## Conventions
- Graph data changes require `python bootstrap/build_graph.py` to rebuild
- Tag changes require re-running `tag_shabads.py` then `build_graph.py`
- Display name changes require `python bootstrap/add_rahao.py` then `build_graph.py`
- `experiments.tsv` logs optimization iterations (suggestion engine tuning)
