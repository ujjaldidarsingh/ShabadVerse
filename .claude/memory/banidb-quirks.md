---
name: BaniDB API Quirks
description: Integration gotchas for BaniDB v2 API - rate limits, data format surprises, caching patterns
type: reference
---

## Rate Limiting
- 429 errors start at ~0.3s per request. Use 0.5s minimum with exponential backoff (0.5, 1, 2, 4s).
- Ang endpoint (`/angs/{n}/G`) tolerates ~2 req/s; individual shabad endpoint (`/shabads/{id}`) is stricter.
- Batch fetching all 1,430 angs takes ~12 min with 0.5s delay. Cache aggressively in SQLite.

## Data Format
- `transliteration` field is a nested dict `{"en": "..."}`, not a string. Always access `.get("en", "")`.
- `translation.en` is also a dict with sub-keys: `bdb` (Dr. Sant Singh Khalsa), `ms` (Manmohan Singh), `ssk`. Use fallback chain: `bdb || ms || ssk`.
- `verse` field is `{"unicode": "..."}` for Gurmukhi text.
- `raag` and `writer` are dicts with `.english` key, not plain strings.

## First Verse is Often a Title
- BaniDB's first verse per shabad is frequently a section header (raag name, mahalla, ghar).
- Examples: "ਸਿਰੀਰਾਗ ਕੇ ਛੰਤ ਮਹਲਾ ੫", "ਡਖਣਾ ॥", "ਪਵੜੀ ॥"
- Fix: Check `is_title_line()` on first verse's transliteration; if title-like, use rahao line or next content verse.

## Ang Endpoint vs Shabad Endpoint
- `/angs/{n}/G` returns all verses on a page with full metadata per verse (transliteration, translation, raag, writer).
- `/shabads/{id}` returns all verses of one shabad with `shabadInfo` metadata.
- For bulk fetching: iterate angs (1-1430), extract unique `shabadId` values, concatenate multi-verse shabads from ang data. Avoids 5,500+ individual shabad API calls.

## Deduplication
- Same `shabadId` appears on multiple angs when a shabad spans pages.
- Deduplicate by `shabadId` when iterating angs; append verses to existing shabad entry.
