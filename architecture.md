# ShabadVerse architecture

The active application is `parkaran-helper`. It serves one Flask workspace at `/` with Explore and Review tabs, plus `/about`. `/explore` and `/reviewer` redirect into that workspace. Personal-library APIs are development-only. Removed legacy page templates were not routed by this application.

## Authority

| Layer | Authority | Derived consumers |
| --- | --- | --- |
| Scripture, verses, translation provider, writer, raag, ang | Preserved BaniDB responses in `shabad_cache.db` | `database/corpus.py`, flattened SGGS JSON, previews and review |
| Concept definitions | `draft_vocabulary.json`, with recorded human confirmation | `build_concept_tags.py` |
| Concept assignments | Generated output `concept_tags.json`, including lexical/inferred status and verse provenance | Full `tags`, vocabulary counts, tag index, evidence panels |
| Discovery presentation | `presentation_tags`, up to six directions per seed | Candidate proposal budget; never truncates evidence |
| Ranking | `build_graph.py` and precomputed `similarity_graph.json` | Neighbor API, cards and Cytoscape |
| AK membership | `sggs_sources.json` | Source filter and preference; 2,078 indexed SGGS shabads |
| Release identity | `release-manifest.json` with content and runtime-code hashes | Image build verification, `/health/ready`, `/api/release` |
| Personal sets | Browser localStorage | Add, reorder, review, save and share |

Curated definitions do not mean every generated assignment is approved. BaniDB is the preserved textual source, not an automated claim that every upstream editorial choice has received local cultural review. Legacy taxonomies, reasoning, backups, and personal-library sources remain historical evidence. They are not interchangeable build inputs.

## Runtime

Flask serves bundled CSS, Cytoscape 3.30.4 and fonts. No CDN is needed. First-letter start/anywhere search reads the local SQLite snapshot. English meaning search and line matching use existing ChromaDB ONNX MiniLM collections; the model must already be cached. A missing model or index must not silently download or create an empty collection. Chroma opens a temporary copy of the vector snapshot because even query operations can update its SQLite state. The release files stay untouched; the process owns and cleans up its disposable copy. Budget disk space for this runtime copy. Ollama is optional and outside the core workflow.

The initial graph response contains compact metadata and tag indexes. Full verses, summaries and provenance load on demand. JSON responses support gzip. Neighbor results have bounded request sizes and a browser cache of 80 contexts, including mode and searched verse. Old faded graph nodes are evicted while the center and set are preserved.

Whole-shabad ranking mixes concept overlap and existing summary/translation embeddings. Core, branch and untagged edges use different ranking formulas, recorded in the graph. Scores are heuristics, not confidence. Line mode returns its anchor and matched verse; an unavailable anchor reports the fallback. Cluster labels must be actual tags on every grouped neighbor. Untagged connections use the neutral label “Translation similarity.”

## Supported candidate build

Run from `parkaran-helper` with dependencies installed from `requirements.txt` constrained by `requirements.lock`:

```bash
python bootstrap/setup.py --source data --output releases/new-candidate
SHABADVERSE_DATA_DIR="$PWD/releases/new-candidate" python app.py
```

The source must be a complete preserved snapshot containing the curated definitions, corpus, BaniDB cache, source index, and both SGGS vector collections. This is an offline rebuild from existing vectors, not a fresh corpus download. Stop source writers before copying the snapshot. Output must be a new directory outside the source. Failure leaves `BUILD_INCOMPLETE`; discard only that failed candidate or investigate it before choosing a new output. The source is never overlaid.

The build retains all lexical anchors, including short verses excluded from embeddings. It records all assignments separately from presentation limits, rebuilds the graph, validates scripture and provenance, and creates a manifest. Original enrichment fields and vectors are preserved; their interpretive influence remains a review consideration.

Direct writers require both `SHABADVERSE_BUILD=1` and an explicit data directory other than `data/`. Legacy taxonomy/enrichment writers additionally require `SHABADVERSE_ALLOW_LEGACY=1`. They are migration tools, not the default recipe. Never use them against a served candidate.

## Verification and release

```bash
SHABADVERSE_TEST_DATA="$PWD/releases/new-candidate" python -B -m unittest discover -s tests -p 'test_*.py'
python release.py verify releases/new-candidate
BASE_URL=http://127.0.0.1:5050 node tests/browser.cjs
```

The browser test needs Playwright and an installed Chromium; `CHROMIUM_PATH` supports an existing executable. It tests phone, tablet and desktop layouts with all external browser requests blocked. Rebuild CSS with `npm ci --ignore-scripts && npm run build:css` after template/utility-class changes. Regenerate the manifest after runtime-code or asset changes, then repeat verification. A manifest records the current content digest as well as HEAD; HEAD alone does not identify uncommitted changes.

For an image, set `SHABADVERSE_DATA_BUILD_DIR=releases/new-candidate` and build the appropriate compose file. Docker copies only enumerated runtime assets and verifies their manifest during the build. It preloads the ONNX model. Compose binds host ports to loopback behind the existing proxy. Image build, health, model availability, and network-isolated runtime checks must pass before release.

Keep the previous image and complete dataset snapshot before any promotion. Stage a new immutable candidate directory, never copy files over live data. Record deployed code digest, dataset ID and image digest. Obtain Ujjal's review of that exact candidate before production promotion. Switch the image only after readiness and smoke checks; rollback selects the retained prior image. No deployment occurred in the September 6 implementation pass.

## Discovery followup, September 7

`api/topics.py` owns full topic pagination, counts, assignment review examples and random starts. Counts come from the complete graph tag index and assignment provenance. `tag_vocabulary.json` records the policy that generated each snapshot. The earlier September 7 candidate retained the historical 35% ceiling and two-times-lexical budget. The evidence candidate removes both membership quotas; every lexical match remains, and inferred assignments use the existing per-concept similarity thresholds. These automatically calibrated thresholds are provisional, including the percentile fallback for description-only concepts. They are not expert acceptance criteria.

`api/source_candidates.py` retrieves additional eligible AK candidates from the preserved SGGS embedding collection. AK-only restricts membership before final selection, including the line-vector query. Prefer AK adds a separate 0.15 ranking preference; returned thematic scores remain unchanged. Source badges include chapter references from the preserved membership index. Missing source data is an explicit failure for AK modes. Browser request/cache context includes source, match mode, selected verse, threshold and viewport neighbor budget.

First-letter browser input converts the supported Roman keyboard mapping before submission. Local search normalizes independent vowels to their Gurmukhi carriers only in search keys. Original scripture and displayed verses are untouched. Input composition and request generations prevent stale search results.

The September 7 review candidate is `releases/2026-09-07-explore`, copied from the September 6 candidate without rebuilding assignments. Only generation-policy metadata was added to its vocabulary. The manifest binds the updated runtime and dataset. After any runtime edit, regenerate and verify it before serving a fresh process. Run both `tests/browser.cjs` and `tests/discovery-browser.cjs` against that process.

## Evidence candidate and review

`releases/2026-09-07-evidence` rebuilds the complete candidate from `releases/2026-09-07-explore`. It preserves all 41,462 previous assignments and adds 47,388 inferred assignments under the existing thresholds. High coverage is visible evidence of model behavior, not proof of thematic accuracy. Graph display budgets remain independent.

`concept_review.json` contains comparison samples, exact verse provenance, the prior assignment-set fingerprint and per-concept thresholds. It is included in the release manifest and image. The review endpoint hides category and score until `reveal=1`; the browser records judgments locally, notes whether status had been revealed, and exports a dataset-bound JSON record. Opening a full shabad exposes current assignment evidence, so this is a review aid rather than a controlled blind study. Selected samples cannot estimate precision.
