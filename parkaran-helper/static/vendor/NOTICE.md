# Bundled frontend dependencies

These assets are served locally. No font or JavaScript CDN is contacted at runtime.

- Cytoscape 3.30.4: https://unpkg.com/cytoscape@3.30.4/dist/cytoscape.min.js (MIT, CYTOSCAPE-LICENSE).
- Tailwind CSS 3.4.17: compiled from the pinned npm lockfile with `npm run build:css` (MIT, node_modules/tailwindcss/LICENSE).
- Space Mono, IBM Plex Mono, Inter, Noto Sans Gurmukhi, Noto Serif Gurmukhi: downloaded from the existing Google Fonts stylesheet on 2026-09-06. Family licenses are included beside this notice.
- `fonts.css` preserves the font family and weight mapping. `fonts/` contains the referenced local font files.

To update assets, change the exact dependency version, compile CSS, retain licenses, and rerun the network-blocked browser test. Regenerate the candidate release manifest after any asset change.
