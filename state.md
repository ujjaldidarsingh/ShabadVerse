# Parkaran Tool Current State

## Status: Active Development (local-first, graph explorer is primary UI)

## Recent Work (2026-03-24 to 2026-03-25)
- Migrated from paid APIs (Anthropic + Voyage AI) to fully local stack (Ollama + sentence-transformers)
- Built SGGS taxonomy: 372 tags across 5,542 shabads (dual-model validated with Qwen 3 + DeepSeek R1)
- Implemented graph explorer with radial tag-clustered layout (Cytoscape.js built-in cose)
- Suggestion engine diversity fix: 2.1 avg clusters per shabad to 8.6 (core/branch pool split)
- Celestial Observatory design system: warm purple-black palette, Noto Serif Gurmukhi, theme-colored nodes
- Full rahao pada extraction (2,623 shabads), display name fix (85 title-like headers corrected)
- Verse preview floating overlay, parkaran trail edges, tuk-aware search
- Code review fixes: XSS (escAttr), race conditions, stale DOM, unbounded cache eviction

## Active Features
- **Explore** (primary): Interactive graph explorer with tag-clustered suggestions, threshold slider, force controls
- **Reviewer**: Parkaran flow review with full Gurmukhi text, shared tags between shabads
- **Database**: Browse/search personal shabad collection (1,035 enriched)
- **Discover**: Search full SGGS via BaniDB first-letter search
- **Builder** (classic): Seed-based parkaran builder with graph-first + vector fallback
- **Occasions**: 10 Sikh occasions with themed shabad suggestions

## Environment
- **Run**: `cd parkaran-helper && python app.py` (port 5050)
- **Python**: miniforge 3.13 (`/opt/homebrew/Caskroom/miniforge/base/bin/python3`)
- **LLM**: Ollama with qwen3:14b (primary) + deepseek-r1:14b (validation)
- **Embeddings**: sentence-transformers all-MiniLM-L6-v2 (384-dim, local)
- **No API keys needed** — fully offline after bootstrap

## Data Assets
- `sggs_all_shabads.json` — 5,542 SGGS shabads with themes, tags, rahao, summaries
- `similarity_graph.json` — precomputed graph (7.4 MB, avg 12.9 neighbors per shabad)
- `tag_vocabulary.json` — 372 validated theme/mood tags
- `enriched_shabads.json` — 1,035 personal library shabads
- `chroma_db/` — ChromaDB with personal (1,035) + SGGS (5,542) collections
- `shabad_cache.db` — SQLite cache for BaniDB API responses

## Known Issues
- Center cluster can get dense when shabad has many tag directions (8+ clusters overlap)
- ~34 shabads still have short/structural display names (edge cases: ਡਖਣਾ, ਪਵੜੀ markers)
- Enrichment pipeline comments still reference Claude/Voyage (cosmetic, code uses Ollama)
- Frontend uses CDN for Tailwind + Cytoscape (requires internet for first load)
