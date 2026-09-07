# Candidate review and promotion evidence

Candidate: `parkaran-helper/releases/2026-09-07-evidence`.

Mechanical validation and human interpretation review are separate. The manifest starts with `cultural_review: pending` and `publish_approval: pending`; build success does not change either status.

Before production approval, record the dataset ID, runtime-code digest and image digest in the approval record. Include reviewer, date, accepted scope and unresolved examples. Do not infer approval from the 44 definition confirmations.

1. Review representative lexical and inferred assignments for every concept, especially Vismad, Birha, Chardi Kala and Nimrata. Inspect the cited verse in the full shabad and distinguish word occurrence from meaning in context.
2. Review restored assignments previously beyond the six-tag cap, plus short-verse anchors excluded from the vector index. Compare their connections with the previous dataset.
3. Review shared-concept, neighbor-concept and untagged connections. Exercise both whole-shabad and line modes, including a searched tuk and an explicit fallback. Assess whether each explanation warrants the suggested connection.
4. Check source text, rahao, writer, raag, ang and translation attribution in reading and review. Automated comparison establishes agreement with the preserved BaniDB snapshot, not independent textual authority.
5. Complete search, read, add, reorder, save, reload and review on a physical phone and tablet. Check large text and both orientations. Report awkward taps, truncated text and lost context with device details.
6. Reconcile production and staging against `/api/release`, the deployment's image digest and the candidate manifest. Build and test the image with runtime network access blocked. Preserve the previous image and complete data snapshot before promotion.

For a questionable connection, record seed ID, neighbor ID, concept, match mode, anchor verse index, dataset ID, observed explanation and proposed correction. Retain the example as a regression case only after its expected result is agreed. Do not use raw ranking scores as the approval criterion.

The next decision is whether the expanded evidence and new connections meet the intended cultural standard. Resolve that on this exact candidate before changing the production dataset.

## Discovery review starting points

Open `/about` for the visible walkthrough and identity. In Explore, open Topics, choose Naam, and expand the assignment-method explanation. “Review examples” mixes lexical anchors, previously retained inferences and newly admitted inferences, with exact cited verses and access to the full shabad. Previous status stays hidden until reveal. Record supported, unsupported or uncertain judgments and export the dataset-bound record. These are review samples, not measured precision or proof that rejected assignments were worse.

| Topic | Total | Lexical | Inferred |
| --- | ---: | ---: | ---: |
| Moh | 1,937 | 738 | 1,199 |
| Naam | 1,937 | 1,864 | 73 |
| Gurmukh | 1,937 | 860 | 1,077 |
| Janam-Maran | 1,937 | 811 | 1,126 |
| Kirpa | 1,937 | 845 | 1,092 |
| Satguru | 1,937 | 1,539 | 398 |
| Sahaj | 1,937 | 715 | 1,222 |

The historical 1,937 limit was floor(0.35 × 5,535). Seven corpus shabads lack line vectors; the full corpus remains 5,542. The new candidate removes this ceiling and the two-times-lexical quota. The similarity thresholds themselves remain unchanged and provisional. The most useful next judgment is whether the retained inferred examples support their concept in context, especially for topics with many more inferred than lexical assignments.

For source behavior, explore one seed, switch between all three Source choices, and inspect AK badges and chapter references. AK-only constrains suggestions; the seed may remain outside AK when selected from the full corpus. In Topics, the separate starting-source filter controls which shabad can be drawn at random.

New candidate totals include Naam 4,107, Karma 4,935 and Kaam 4,769. High counts alone neither validate nor invalidate a concept assignment. Review the newly admitted examples in context before setting expert acceptance criteria. No cultural approval is inferred from the instruction to merge product changes.
