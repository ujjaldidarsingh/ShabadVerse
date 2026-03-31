# Parkaran Tool Current State

## Status: Active Development — Design Polish Pass

## Recent Work
- 2026-03-30: Design review (7.8/10), began fix pass — reviewer inline styles, touch targets, Gurmukhi-first
- 2026-03-29: SAVE/LIBRARY on reviewer page, parkaran library (localStorage), GitHub repo + ngrok demo
- 2026-03-25: Graph explorer, SGGS taxonomy (372 tags, 5,542 shabads), suggestion engine diversity
- 2026-03-24: Local stack migration (Ollama + sentence-transformers), Celestial Observatory design

## Active Pages
- **Explore** (primary): Interactive graph explorer with tag-clustered suggestions, threshold slider, force controls
- **Reviewer**: Parkaran flow review with full Gurmukhi text, shared tags between shabads
- **Database**: Browse/search personal shabad collection (1,035 enriched)

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
- DESIGN.md color tokens drift from actual CSS values (documentation, not code bug)

## Milestones

### Alpha (internal testing ready)
- [x] feat: graph explorer with radial tag-clustered layout (Cytoscape.js)
- [x] feat: SGGS taxonomy — 372 tags across 5,542 shabads
- [x] feat: suggestion engine with core/branch diversity (8.6 avg clusters)
- [x] feat: threshold slider for suggestion selectivity
- [x] feat: force controls (center, repel, link, distance)
- [x] feat: verse preview overlay with rahao highlighting
- [x] feat: parkaran trail (green directed edges between selected shabads)
- [x] feat: reviewer page with shared tag transitions
- [x] feat: first-letter search (BaniDB) + local tag/theme fallback
- [x] feat: parkaran library save/load/delete (localStorage)
- [x] feat: SAVE/LIBRARY on reviewer page
- [x] bug: fix cose-bilkent crash — built-in cose layout
- [x] bug: fix XSS via single-quote injection in onclick attributes
- [x] bug: fix race condition in expandShabad (concurrent guard)
- [x] bug: searched tuk drives suggestions via blended vector+graph path
- [x] bug: 8 structural display names fixed (12 remaining are genuine section markers)
- [x] feat: shabad preview popup visible in tooltip (PREVIEW button prominent)
- [x] chore: GitHub repo + ngrok demo deployment
- [x] design: Gurmukhi-first display on database page
- [x] design: Reviewer header uses CSS classes (not inline styles)
- [x] design: Touch targets meet 44px minimum (buttons, breadcrumbs, slider)
- [x] design: NO SHARED TAGS uses dim color (not red)
- [x] design: Consistent button styling across all pages

### Beta (external testing ready)
- [x] design: Celestial Observatory design system (DESIGN.md)
- [x] design: warm purple-black palette, Noto Serif Gurmukhi, theme-colored nodes
- [ ] design: font size overhaul — explore/review pages readable at arm's length
- [ ] design: tooltip dialog box sizing (verses/preview too small currently)
- [ ] design: tag labels fully visible (max-width reactive, wrap not truncate)
- [ ] design: reviewer detail panel max-width for readability
- [ ] design: tag label collision avoidance on graph
- [ ] feat: shabad labels show 4-5 Gurmukhi words (not 2)
- [ ] feat: add-to-parkaran solidifies nodes with visual trail breadcrumbs
- [ ] feat: tag taxonomy refinement (merge overlapping tags)
- [ ] test: automated smoke test for all API endpoints
- [ ] test: graph neighbor diversity regression test (experiments.tsv baseline)
- [ ] perf: bundle Tailwind + Cytoscape locally (no CDN dependency)
- [ ] docs: user guide — how to search, explore, build parkaran, review

### Ship (production deploy)
- [ ] perf: lazy-load similarity_graph.json (7.4 MB blocks initial page load)
- [ ] perf: graph node eviction strategy (cap visible nodes after 20+ expansions)
- [ ] perf: cache SentenceTransformer model load at app startup
- [ ] feat: export parkaran as PDF/image/share link
- [ ] feat: occasion-aware suggestions integrated into explore view
- [ ] design: mobile responsive graph explorer (touch gestures, pinch zoom)
- [ ] design: accessibility pass (focus-visible, screen reader labels, contrast ratios)
- [ ] docs: deploy guide (Docker, systemd, or similar)
- [ ] docs: bootstrap pipeline runbook (recovery from partial failures)
- [ ] test: E2E browser tests (Playwright or similar)
