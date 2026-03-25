# DESIGN.md — Parkaran Tool Design System

## Identity
**Product:** Parkaran — Sikh keertan set builder and SGGS thematic explorer
**Audience:** Sikh keertan musicians, raagi jathas, scholars
**Personality:** Reverent, precise, data-dense. Bloomberg terminal meets sacred text.
**Classifier:** APP UI (workspace-driven, data-dense, task-focused)

## Color System

### Dark Mode (primary, only mode)
| Token | Value | Usage |
|-------|-------|-------|
| `--bg-deep` | `#030712` / `rgb(3,7,18)` | Page background |
| `--bg-surface` | `#0a0f1a` / `rgb(10,15,26)` | Cards, panels, sidebar |
| `--bg-elevated` | `rgba(255,255,255,0.016)` | Subtle elevation (grid lines) |
| `--accent` | `#f59e0b` / `rgb(245,158,11)` | Primary accent (amber) — all interactive elements |
| `--accent-muted` | `rgba(245,158,11,0.15)` | Hover states, subtle highlights |
| `--accent-text` | `#fbbf24` / `rgb(251,191,36)` | Gurmukhi text, active labels |
| `--accent-bright` | `#fef08a` / `rgb(254,240,138)` | Emphasis highlights |
| `--text-primary` | `#e5e7eb` / `rgb(229,231,235)` | Body text |
| `--text-muted` | `#4b5563` / `rgb(75,85,99)` | Secondary info, metadata |
| `--text-dim` | `#374151` / `rgb(55,65,81)` | Tertiary, disabled |
| `--success` | `rgba(16,185,129,0.8)` | In-parkaran state (emerald) |
| `--border` | `rgba(255,255,255,0.06)` | Subtle dividers |

### Rules
- No pure white (`#fff`) for text — use `--text-primary` (~off-white)
- No pure black backgrounds — use `--bg-deep` (navy-black)
- Accent is always amber — no secondary accent color
- Success/parkaran state is emerald green — only used for "in set" indicators
- Grid lines use `--bg-elevated` for the subtle cell pattern

## Typography

### Font Stack
| Role | Font | Fallback | Usage |
|------|------|----------|-------|
| Script | `Noto Sans Gurmukhi` | sans-serif | All Gurmukhi text (shabads, rahao, titles) |
| HUD / Controls | `IBM Plex Mono` | monospace | Metadata, controls, stats, labels |
| Branding | `Space Mono` | monospace | Logo "PARKARAN", nav items, section headers |
| Body | System sans-serif | — | Summaries, translations, descriptions |

### Scale
| Element | Size | Weight | Font |
|---------|------|--------|------|
| Nav brand | 14px | 700 | Space Mono |
| Nav links | 12px | 400 | Space Mono |
| Section headers | 12px | 700 | Space Mono |
| Page titles | 20px | 700 | Space Mono |
| Gurmukhi (graph nodes) | 6px | 400 | Noto Sans Gurmukhi |
| Gurmukhi (tooltip/cards) | 13px | 400 | Noto Sans Gurmukhi |
| Gurmukhi (shabad preview) | 16px | 400 | Noto Sans Gurmukhi |
| Tag labels (graph) | 9px | 600 | IBM Plex Mono |
| Metadata | 9-10px | 400 | IBM Plex Mono |
| Body text | 13px | 400 | System sans |
| Stats counter | 10px | 400 | IBM Plex Mono |

### Rules
- Gurmukhi script always renders in `Noto Sans Gurmukhi` — never system sans
- Transliterations are secondary, never the default display
- All uppercase text uses `letter-spacing: 0.05em` minimum
- Tag labels match Gurmukhi display size (same visual weight)
- No text below 8px anywhere in the app

## Spacing

### Base Unit: 4px
| Token | Value | Usage |
|-------|-------|-------|
| `xs` | 4px | Inline padding, icon gaps |
| `sm` | 8px | Component internal padding |
| `md` | 12px | Between related items |
| `lg` | 16px | Between sections |
| `xl` | 24px | Major section gaps |
| `2xl` | 32px | Page-level spacing |

### Rules
- All spacing must be a multiple of 4px
- Cards: 12px internal padding
- Sidebar: 8px item gap
- Graph area: full-bleed, no padding (canvas fills available space)

## Components

### Graph Node (Cytoscape)
- Default: 8px circle, `rgba(170,170,190,0.6)` fill, no border
- Repertoire: 10px, amber fill `rgba(245,158,11,0.7)`
- Center: 14px, bright amber `rgba(245,158,11,0.9)`
- In-parkaran: 10px, emerald fill `rgba(16,185,129,0.8)`
- Selected: 12px, amber fill

### Graph Edge
- Width: 0.6px
- Color: `rgba(170,170,190,0.15)`
- Style: `unbundled-bezier` with 15px control distance
- Faded: opacity 0.08

### Tooltip (HUD)
- Width: 240px, max
- Background: `rgba(5,10,20,0.95)`
- Border: 1px `rgba(245,158,11,0.15)`
- Corner radius: 6px
- Position: clamped to viewport, offset 24px from node

### Search Input
- Background: `rgba(10,15,26,0.97)`
- Border: 1px `rgba(245,158,11,0.15)`, brightens on focus
- Height: 38px (should be 44px — known issue)
- Placeholder: `IBM Plex Mono`, muted gray
- Prefix: amber `>` cursor character

### Buttons
- Primary (filled): amber bg, dark text
- Ghost: transparent bg, amber text, amber border on hover
- Small controls: `IBM Plex Mono` uppercase, 9-10px

### Parkaran Sidebar
- Fixed right column, 200px wide
- Header: "PARKARAN" with count badge
- Items: draggable, numbered, Gurmukhi title + transliteration subtitle
- Remove button: `x` that turns red on hover

## Layout

### Explore Page (primary)
```
[─────────── HEADER (48px) ───────────]
[SEARCH] [TAGS] [RANDOM]   [THRESHOLD]
[                        ][PARKARAN   ]
[                        ][SIDEBAR    ]
[     GRAPH CANVAS       ][           ]
[     (full height)      ][           ]
[                        ][           ]
[SPREAD SLIDER] [FIT][RST][REVIEW BTN ]
```

### Other Pages
Standard layout: header + content area, no sidebar.
Max content width: 1200px with auto margins.

## Motion

### Transitions
- Graph node animation: 400ms ease-out-cubic
- Tooltip show: 200ms fade-in
- Breadcrumb highlight: instant (no transition)
- Layout re-run: 600ms animated via Cytoscape cose

### Rules
- `prefers-reduced-motion` not yet implemented (TODO)
- Only animate `opacity` and `transform` on DOM elements
- Graph animations use Cytoscape's built-in easing, not CSS

## Accessibility (known gaps)

- Touch targets below 44px: nav links (25px), FIT/RESET buttons (21px), slider (16px)
- No `focus-visible` ring on graph controls
- No ARIA labels on graph canvas
- Gurmukhi text has no `lang="pa"` attribute
- No skip-to-content link
- Color contrast on muted text (`#4b5563` on `#030712`) may fail WCAG AA

## Anti-Patterns (do NOT introduce)

- No purple/violet/indigo — amber is the only accent
- No colored left-border cards
- No decorative blobs or wavy dividers
- No emoji in UI (Ik Onkar symbol is the only icon-like element)
- No centered-everything layouts — left-align by default
- No generic SaaS patterns (3-column feature grids, hero sections)
- No transliteration-first displays — Gurmukhi is always primary
