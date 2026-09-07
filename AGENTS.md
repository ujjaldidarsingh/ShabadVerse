# ShabadVerse

The active app is `parkaran-helper`: a local-first SGGS explorer and parkaran builder for 5,542 shabads. Read `architecture.md`, `state.md`, and `DESIGN.md` before changes.

The current candidate uses 44 human-curated concept definitions. Generated assignments require separate review. Preserve Gurbani text, provenance, curated definitions, source membership and archived data. Never truncate evidence to reduce graph clutter.

Use the supported offline candidate build in `architecture.md`. Do not run the historical setup/enrichment/taxonomy sequence against `data/`. Keep candidates separate and verify their manifest before serving or packaging. Production promotion requires review of the exact candidate.

Flask, ChromaDB ONNX MiniLM, SQLite, bundled Tailwind/Cytoscape and vanilla JavaScript form the active stack. The core browser workflow needs no CDN. `SHABADVERSE_DATA_DIR` selects a complete candidate. Ollama and development-only personal-library APIs are not prerequisites for Explore and Review.

Touch workflows on phones and tablets take priority. Full keyboard-only operation is not required for this pass; preserve useful labels and native controls.
