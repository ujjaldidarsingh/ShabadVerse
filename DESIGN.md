# ShabadVerse interaction and design contract

ShabadVerse supports discovering a connection, reading the full shabad, choosing a sequence and reviewing it. Gurmukhi stays primary. Summaries, inferred concepts and ranking are navigation aids with visible provenance.

Phone and tablet use is a product requirement. A complete keyboard-only workflow is not a release requirement for this implementation, per Ujjal's direction. Keep native button semantics and labels because they also support touch assistive technology. This does not claim WCAG conformance.

Graph is the default on every screen. A deliberate Cards choice persists; old automatic phone defaults do not override the new default. Cards and Graph use the same neighbor API. The phone navigation exposes Explore, Review and My set. Add, read, explore, remove and move earlier/later are explicit tap actions; drag is optional. Search distinguishes first letters from the start, first letters anywhere, transliteration and English meaning. Whole-shabad and line matching are a separate visible control. A line match shows the selected verse and the reason for any fallback.

Reading must work without hover. Core new action targets are at least 44 CSS pixels. Preview and review show full Gurbani, translations and lexical/inferred evidence. Do not equate a high score or lexical word match with theological correctness. Untagged neighbors retain a neutral explanation.

`parkaran-helper/static/css/style.css` is authoritative for the dark and light tokens, responsive breakpoints and type scale. `tailwind.config.js` defines generated utility extensions. Local `static/vendor/fonts.css` records the actual family/weight mappings. This document deliberately does not duplicate numeric tokens that can drift.

Keep the graph for spatial exploration, with bounded history and a cards alternative. Do not require the graph canvas to carry the complete phone workflow. Native packaging, offline installation, cross-device sync and app-store distribution remain separate work; this responsive web candidate does not yet establish those capabilities.

Before shipping, inspect actual phones and tablets with larger text, portrait/landscape rotation, touch scrolling and screen-reader reading. Browser emulation is evidence of layout and actions, not proof of device behavior or cultural suitability.

## September 7 discovery update

The header keeps “How it works” visible on every screen. `/about` is an interactive, three-step walkthrough using preserved Gurbani and actual candidate connections. Product copy follows Ujjal's voice profile and keeps generated interpretation distinct from scripture. The identity combines a drawn S-and-connections mark with a serif wordmark and restrained gold accents. The mark does not borrow a sacred glyph.

The graph displays at most six suggestions on phones, twelve on tablets and twenty-four on desktops. This is a display budget, not a membership or evidence limit. Topic pages expose every assigned shabad through pagination. Full verses remain available by tapping a node or a topic entry.

“Source” controls suggested connections: All SGGS, Prefer Amrit Keertan, or Amrit Keertan only. Topic selection separately controls the source of the starting shabad. The origin label and “Try another” retain that topic and source. AK badges identify indexed membership; preference never relabels a thematic score as stronger evidence.
