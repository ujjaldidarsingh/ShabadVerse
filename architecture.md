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

AK source-specific retrieval, ranking and presentation were removed at Ujjal’s request. Legacy source query parameters have no effect. Source membership remains in the preserved dataset and release validation, but is not exposed by discovery, reading or topic APIs.

First-letter browser input converts the supported Roman keyboard mapping before submission. Local search normalizes independent vowels to their Gurmukhi carriers only in search keys. Original scripture and displayed verses are untouched. Input composition and request generations prevent stale search results.

The September 7 review candidate is `releases/2026-09-07-explore`, copied from the September 6 candidate without rebuilding assignments. Only generation-policy metadata was added to its vocabulary. The manifest binds the updated runtime and dataset. After any runtime edit, regenerate and verify it before serving a fresh process. Run both `tests/browser.cjs` and `tests/discovery-browser.cjs` against that process.

## Two matching algorithms (October 2 candidate)

Whole-shabad matching reads the precomputed graph and labels clusters with concepts. Line matching is separate. It embeds the anchor verse's BaniDB English, ranks other verses by cosine similarity alone, keeps the best verse per shabad, and skips headings and verbatim refrains. It never applies concept labels or a concept prior. Its optional label is a Gurmukhi word both verses contain: at least three letters once one final vowel sign or nasal is dropped, found in at most 1% of verses, not on a short stoplist, and shared by at least two matches. `database/corpus.py` defines the rahao marker, the rahao span (the marked verse plus up to three verses before it, back to a stanza end or heading) and heading detection.

`bootstrap/build_concept_tags.py` annotates each assignment with `weight`, `weight_verses` and `central`; its constants define the interim rule. Weights never change membership, and the build fails if a verse adds weight to a concept the shabad lacks. `release.validate` checks weight ranges. `api/topics.py` orders topics and draws random starts from these fields.

## Concept vocabulary and word senses (October 13 candidate)

`parkaran-helper/data/draft_vocabulary.json` is the curated vocabulary, under version control. Each concept carries Ujjal's dated rulings. `word_senses` lists words whose sense decides the concept: for a token starting with the word (longest word first), the first sense whose `english_any` pattern appears in the verse's BaniDB English, and whose `english_none` pattern does not, decides. A word with no matching sense counts for nothing. One spelling can therefore support two concepts, as ਦਇਆ does for Daya (human) and Daya (divine). Split concepts use one word in parentheses. Two optional settings guard calibration: `infer: false` counts word evidence only, for a word sense such as Sahaj (ease); `calibration: description` keeps a concept's threshold on its description while its words still count, for words too few or varied to calibrate on (Nimrata). `bootstrap/setup.py --vocabulary data/draft_vocabulary.json` builds a candidate from a preserved snapshot with the revised vocabulary, so snapshots are never edited. `tests/test_vocabulary.py` keeps Ujjal's ruled examples as regression cases.

## Meaning search (October 13 search candidate)

`api/meaning_search.py` serves `/api/graph/semantic-search`. It fuses five local lists by weighted reciprocal rank (k = 60). Each entry is one shabad with the verse that matched, so choosing a result opens line matching from that verse.

1. Typed line: words typed in English letters against each verse's BaniDB transliteration. Both sides reduce each word to a consonant skeleton: vowels go, every n after a word's first letter goes, and spellings of one letter merge (`Th`, `dh`, `chh`). A verse must hold five consonants of the typed line in order and at least half of it.
2. Gurmukhi words, matched at word starts.
3. Concept names in English letters or Gurmukhi, through the concept weights. `word_senses` in the curated vocabulary decide what a Gurmukhi word names; ਕਾਮਣਿ names nothing. Extra English-letter spellings are a hand-kept list in the module.
4. Verse translations by meaning (`sggs_lines`). When a typed line finds a verse holding 80% of it, that verse's English replaces the query here.
5. Machine summaries by meaning (`sggs_shabads`), skipping summaries that only report missing text.

Typed matches weigh three times, scaled by the share of the line their verse holds. A query made only of concept names weighs its concept list three times. Titles that `corpus.HEADING` misses are excluded inside this module only. The verse index, about 60,000 verses and 20 MB, is read from the BaniDB cache once; `wsgi.py` builds it in a background thread at startup.

Claude Haiku 5.5 reordering runs only with `ANTHROPIC_API_KEY` and `SHABADVERSE_RERANK=1`. The browser asks for it after a 0.7 second pause, while the local order is already on screen. The server sends the query and up to 30 candidates: each matched verse's BaniDB English and transliteration, plus the rahao. It uses thinking off, low effort and a JSON schema. Unknown ids are dropped. A refusal, error, timeout or limit returns the local order. Orders are cached per query. The limits are 30 reorderings per visitor per ten minutes and `SHABADVERSE_RERANK_DAILY_CAP` per day per process, default 2,000; an Anthropic Console spending limit is the hard backstop. `/about` states what leaves the server when the flag is on. `audits/2026-10-13-search/` holds the evaluation.

## Evidence candidate and review

`releases/2026-09-07-evidence` rebuilds the complete candidate from `releases/2026-09-07-explore`. It preserves all 41,462 previous assignments and adds 47,388 inferred assignments under the existing thresholds. High coverage is visible evidence of model behavior, not proof of thematic accuracy. Graph display budgets remain independent.

`concept_review.json` contains comparison samples, exact verse provenance, the prior assignment-set fingerprint and per-concept thresholds. It is included in the release manifest and image. The review endpoint hides category and score until `reveal=1`; the browser records judgments locally, notes whether status had been revealed, and exports a dataset-bound JSON record. Opening a full shabad exposes current assignment evidence, so this is a review aid rather than a controlled blind study. Selected samples cannot estimate precision.

## Current production operation

The September 7 SGGS-only release is live at `shabadverse.com`, from merged PR #22. Production uses the immutable image `shabadverse:2026-09-07-sggs` and the compose file `/opt/shabadverse-releases/2026-09-07-sggs/compose.production.yml`, project `parkaran-helper`. Caddy still routes to loopback port 5050. Use this release compose file for restarts; the checkout's historical `data/` is not the deployed candidate and is not a rebuild source.

The image passed full manifest verification at build time. With networking disabled, core APIs, semantic search and both matching modes passed, followed by unchanged asset/code hashes. The post-query check avoids loading a second full corpus beside the active indexes. The production container has a 900 MiB limit; observed use after browser checks was about 719 MiB with no restart.

Rollback assets are retained at `/opt/shabadverse-backups/2026-09-07-pre-evidence`, including the prior runtime data, container configuration and Caddy configuration. The prior image is tagged `shabadverse-rollback:2026-09-07`. To roll back, use the current release compose file with an override selecting that image and `mem_limit: 1200m`, then recreate the service with the same `parkaran-helper` project. Check `/` and a known search; the old image does not expose the new readiness endpoint. The saved runtime-data snapshot is available if recovery of changes made inside the previous container is needed.

Staging is running its earlier image again. Its data intentionally differs from the new production candidate; it is retained as a comparison baseline. The deployment receipt is `deployments/2026-09-07-evidence.json`.

For the immediately preceding release, use `/opt/shabadverse-backups/2026-09-07-pre-sggs/compose.production.yml` with project `parkaran-helper`; its image is retained as `shabadverse:2026-09-07-evidence` and `shabadverse-rollback:2026-09-07-evidence`. Current release identity is recorded in `deployments/2026-09-07-sggs.json`.
