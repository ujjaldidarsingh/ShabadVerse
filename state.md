# ShabadVerse state, October 13, 2026

## Concept alignment (candidate, not deployed)

Ujjal confirmed all 44 concept cards on October 13 (39 agreed, 5 changed). `audits/2026-10-09-concept-alignment/RESULTS.md` records what changed and why. The curated vocabulary, `parkaran-helper/data/draft_vocabulary.json`, now holds 48 concepts with dated rulings: Daya, Daan and Sach split into (human) and (divine), Sahaj into (poise) and (ease), and seven words are judged by their sense in the verse's translation. Candidate `parkaran-helper/releases/2026-10-13-alignment` is built from the phase 1 snapshot with `bootstrap/setup.py --vocabulary`. Its runtime code is the committed phase 1 code. Kaam's members fell from 4,769 to 320, and word evidence scores 93% against Ujjal's earlier verse labels, up from 89%. Agreement with his central-concept picks is unchanged at about a third; calibrating thresholds and the per-verse rule against his labels is the next step. Nothing here is committed or deployed yet.

## Matching redesign phase 1 (candidate, not deployed)

Production is unchanged; see the September 7 release below. This work follows `audits/2026-09-30-matching-strategy/STRATEGY.md` and is uncommitted on branch `phase1-line-matching-topic-weights`.

- `shabad_cache.db` was restored from the host into all four release directories (SHA-256 `fdbaecd8…`, matching every manifest). Keep a second copy off the host.
- Line matching is now its own algorithm: cosine similarity of verse translations only, the best verse per shabad, no concept prior and no concept clusters. Matches group under a rare Gurmukhi word shared with the anchor when at least two share it, otherwise under "Similar translation". The default anchor is the marked rahao, skipping headings. A searched verse opens line matching. Each mode keeps its own strictness (whole shabad 0.35, line 0.5).
- Every concept assignment carries a provisional weight (0 to 100, rahao verses counted three times, each verse counting toward at most its two strongest concepts) and a central flag (top two by weight, at least 20). Membership, presentation tags and the graph are unchanged.
- Topic lists start with shabads that center on the topic. Within each tier, shabads that use the word come before inferred ones, then heavier weights. Random topic starts draw from central shabads when there are any. Kaam now opens with Ang 1358 (ਹੇ ਕਾਮੰ ਨਰਕ ਬਿਸ੍ਰਾਮੰ); shabad 1 is 4,474th of 4,769.
- Candidate `parkaran-helper/releases/2026-10-02-phase1` (dataset `dd79bddf182e6cf7…`) was built with `bootstrap/setup.py` from `2026-09-07-explore`. Membership, assignment order and graph neighbors match `2026-09-07-sggs`. The only differences are float32 noise in thresholds (at most 1.2e-7), the order inside `shared_tags` lists, and one tied evidence verse (shabad 4603, Satguru).
- 36 Python checks, including the dataset checks, and both browser suites pass against the candidate on phone, tablet and desktop.
- Ujjal's review sets: `audits/2026-10-02-review-sets/`, served as a private page (https://claude.ai/artifact/Fdo93Mwweb7DTDSniuY7iW). All 458 judgments were complete on October 9; see `RESULTS.md` there. Line matching: translation-only ties the live method (68% same or related for both). Central concepts from verse evidence agree with Ujjal in 35% of shabads against a 75% bar, and 21 of his 69 picks were never assigned. Word matches are 90% right, and inferred evidence is reliable only as each verse's strongest concept.

## September 7 production release

Current production release: `parkaran-helper/releases/2026-09-07-sggs`, merged through PR #22. AK preference, AK-only filtering, badges, chapter labels and topic membership counts are removed. Old source preferences and query parameters no longer affect results. The dataset is byte-identical to the evidence candidate; archived source membership remains preserved. The new runtime SHA-256 is `3f2480975ddd3681ebb1b85d77e2d03a898b8a2166dd337b7124332ba2c80269`. The deployment and rollback record is `deployments/2026-09-07-sggs.json`.

27 Python checks and both browser suites pass on local and public production across phone, tablet and desktop. The complete image passed network-isolated API checks and unchanged post-query hashes.

## Earlier evidence release

Latest implementation: `parkaran-helper/releases/2026-09-07-evidence`. Both membership quotas are removed. The candidate contains 88,850 assignments, preserving all 41,462 previous assignments. Newly admitted inferences remain provisional. Topic review hides previous inclusion status until reveal and supports local judgments and export. The earlier September 7 snapshot below remains preserved.

Before this deployment, production exposed 248 tags and staging 44; neither exposed `/api/release`. The host is confirmed at 18.220.187.85. Production ran commit de5e13f with image 82ef1d1d0287; its image and runtime data were retained for rollback. PR #21 is merged and production now serves the evidence candidate. Both browser suites pass against the public site. Staging was restarted on its previous image and remains an earlier baseline.

32 Python checks pass against the evidence candidate, including full-corpus provenance, lexical retention, uncapped membership and hidden review status and serialized vector initialization. Both browser suites pass on phone, tablet and desktop, including simultaneous cold-start requests with external browser requests blocked. The rebuilt graph averages 3.5 stored neighbors per shabad; this is a presentation outcome, not a measure of thematic accuracy.

Production dataset ID: `297917b9d8409227b1e7252b30f7e3952d085052b04a612ababdb4da18ed1ac5`. Runtime SHA-256: `24ef9bb83888c9d8878834f2c7bcb3b95598e7c647f0bed046a5c11938501b79`. The exact image, checks and rollback location are recorded in `deployments/2026-09-07-evidence.json`. Local preview `http://127.0.0.1:5052` serves the same dataset.

## Earlier September 7 candidate

Current review candidate: `parkaran-helper/releases/2026-09-07-explore`. The seven requested discovery changes are implemented: visible voice-reviewed walkthrough, repaired Roman/Gurmukhi initial search, Graph default, new visual identity, effective AK source choices, explained topic ceilings with review examples, and random starts within a complete topic. Topic pagination removes the old first-page-only browsing limit.

Twenty-nine Python tests pass, including full-corpus checks. Both browser suites pass on phone, tablet and desktop with external browser requests blocked. The browser checks cover initial-search equivalence, source modes, pagination, review examples, topic random starts, deliberate view persistence, and the existing complete parkaran workflow. Physical-device and cultural judgments remain with Ujjal. No remote deployment occurred.

The corpus, graph, assignments and source membership match the September 6 candidate. Added vocabulary metadata records the existing generation policy. See the current manifest for exact runtime and dataset hashes. Historical September 6 digests below identify that earlier candidate, not the current runtime.

Current dataset ID: `d1dfb424ae38f840a621097baeef8a246b6f5dc7d83e09910a8741be64fc511d`. Runtime SHA-256: `17b8b7561ab487d763d09e30d8353f7ce77e769f503a6a759a587456175046a5`. Local preview: `http://127.0.0.1:5052`.

## September 6 baseline

Implementation candidate: `parkaran-helper/releases/2026-09-06-trust-mobile`. This directory is ignored by git and has not replaced `data/`. The working code is uncommitted on `batch-8-9-staging`, based on `f14d66310298aa45c4b8ae5aaaa801c127c6fe7e`. Use the manifest's code digest to identify the actual candidate.

## Implemented

- Full concept assignments and lexical anchors are retained, with a separate six-direction presentation budget. The rebuilt graph uses bounded scores and truthful cluster labels, including a neutral untagged path.
- Local first-letter search preserves start/anywhere semantics and selected-verse context. Visible line/whole-shabad matching, explicit fallback, request bounds and context-aware caches protect the exploration path.
- Phone cards, a set drawer, tap reorder controls, full reading and review provide the core touch workflow. Graph exploration remains available.
- Evidence panels distinguish lexical and inferred assignments; lower-confidence description-only concepts remain visible. Writer and verse records come from the preserved cache. Machine summaries are labelled.
- Frontend assets are local. Initial metadata is smaller, gzip is supported, neighbor caching and faded graph history are bounded.
- Candidate builds preserve the source directory, guard legacy writers and validate a hashed runtime bundle. Docker uses enumerated assets, pinned dependency constraints, loopback bindings and readiness checks.
- Unrouted legacy templates and their unused page scripts were removed. Curated data, historical taxonomies, backups and personal-library sources remain preserved.

## Deployment evidence

Public `/api/graph/init` responses observed on September 6 still differ: production exposes 248 tags and 15.9 average neighbors; staging exposes 44 tags and 19.6 average neighbors. Both expose metadata for 5,542 shabads. These responses identify data behavior, not remote commit or image digests. The remote code, image and full dataset hashes have not been reconciled. Neither environment was edited or deployed during this pass.

The old topology documentation names Lightsail with Caddy proxying production port 5050 and staging 5051. Treat server paths and image claims as historical until checked on the host. The supported promotion sequence is in `architecture.md`; it supersedes the former overlay-then-backup instructions.

## Remaining release gates

The expanded assignments and changed neighbor distribution require review of the exact candidate. Existing confirmation of concept definitions does not approve these outputs. Record review separately from mechanical validation. See `REVIEW.md`.

Docker is unavailable on this workstation, so the image build and isolated container runtime remain unverified. Browser emulation does not establish native-app readiness or physical-device accessibility. Native packaging, installable offline use and cross-device sync have not been implemented.

Do not add taxonomies, generated commentary, occasion workflows, graph animation features or cloud synchronization before validating the current discovery-to-review journey and resolving data/deployment identity. Keep the preserved snapshots until their authority and recovery value have been traced.

## Verification evidence

Seventeen Python tests pass, including full-corpus identity/provenance, lexical retention, all-seed cluster truth, build guards and writable-vector isolation. Chromium checks pass at 390×844, 820×1180 and 1440×1000 with external browser requests blocked: first-letter search, matching modes, read, add, reorder, review, reload, shared order and bounded graph history. Release assets stayed byte-identical after semantic searches and browser use. Python dependency resolution passed without installation. The existing global Python environment emits a RequestsDependencyWarning; a clean Docker runtime is still untested.

The candidate contains 41,462 assignments across 44 concepts and averages 8.23 stored neighbors per shabad. This changed distribution is a review subject, not a quality score. Original corpus and graph hashes match the pre-implementation snapshot.

Dataset ID: `cbecdf8a3b27e4d6760b61e4a9215823ac4706e557cbf3e6d4810d2848417a23`.
Runtime-code SHA-256: `57f9e01679b128ef30bdb8a70f53aae033246e12866b23b112a082866d4033b5`.
