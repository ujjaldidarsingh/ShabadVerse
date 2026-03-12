"""Main enrichment pipeline: BaniDB matching → Claude themes → save."""

import sys
import os
import json

# Add parent dir to path so config is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from enrichment.data_loader import load_from_excel, save_enriched, load_enriched
from enrichment.banidb_matcher import BaniDBMatcher
from enrichment.claude_enricher import ClaudeEnricher


def run_enrichment():
    """Run the full enrichment pipeline."""
    os.makedirs(config.DATA_DIR, exist_ok=True)

    # Always load fresh from Excel to pick up new rows
    print("Loading shabads from Excel...")
    excel_shabads, keertanis = load_from_excel()
    print(f"  Excel has {len(excel_shabads)} shabads, {len(keertanis)} keertanis")

    # Merge with existing enriched data if available
    if os.path.exists(config.ENRICHED_DATA_PATH):
        print("Merging with existing enriched data...")
        existing_shabads, _ = load_enriched()
        # Build lookup of existing enrichment by title+keertani
        existing_lookup = {}
        for s in existing_shabads:
            key = (s["title"].lower().strip(), (s.get("keertani") or "").lower().strip())
            existing_lookup[key] = s

        # Merge: keep existing enrichment, add new shabads
        merged = 0
        for s in excel_shabads:
            key = (s["title"].lower().strip(), (s.get("keertani") or "").lower().strip())
            if key in existing_lookup:
                existing = existing_lookup[key]
                # Copy enrichment fields from existing
                for field in [
                    "ang_number", "sggs_raag", "writer", "gurmukhi_text",
                    "english_translation", "transliteration", "banidb_shabad_id",
                    "primary_theme", "secondary_themes", "occasions", "mood",
                    "brief_meaning", "match_confidence", "enrichment_status",
                ]:
                    if existing.get(field) is not None:
                        s[field] = existing[field]
                merged += 1

        new_count = len(excel_shabads) - merged
        print(f"  Kept enrichment for {merged} existing shabads, {new_count} new to process")

    shabads = excel_shabads
    save_enriched(shabads, keertanis)

    # Phase 1: BaniDB matching
    print(f"\n{'='*60}")
    print("PHASE 1: BaniDB Matching")
    print(f"{'='*60}")
    phase1_banidb(shabads, keertanis)

    # Phase 2: Claude theme extraction
    print(f"\n{'='*60}")
    print("PHASE 2: Claude Theme Extraction")
    print(f"{'='*60}")
    phase2_themes(shabads, keertanis)

    print(f"\n{'='*60}")
    print("ENRICHMENT COMPLETE")
    enriched = sum(1 for s in shabads if s["enrichment_status"] == "complete")
    banidb_matched = sum(1 for s in shabads if s.get("banidb_shabad_id"))
    print(f"  BaniDB matched: {banidb_matched}/{len(shabads)}")
    print(f"  Fully enriched: {enriched}/{len(shabads)}")
    print(f"  Data saved to: {config.ENRICHED_DATA_PATH}")


def phase1_banidb(shabads, keertanis):
    """Match all shabads against BaniDB."""
    matcher = BaniDBMatcher()

    pending = [s for s in shabads if not s.get("banidb_shabad_id")]
    print(f"Shabads to match: {len(pending)} (already matched: {len(shabads) - len(pending)})")

    for i, shabad in enumerate(pending):
        idx = shabad["id"]
        title = shabad["title"]
        print(f"[{i + 1}/{len(pending)}] Searching for \"{title}\"...", end=" ")

        result = matcher.match_shabad(title)

        if result:
            for key, value in result.items():
                shabad[key] = value
            print(
                f"✓ Ang {result.get('ang_number')}, "
                f"{result.get('sggs_raag', 'Unknown Raag')}, "
                f"confidence: {result.get('match_confidence', 0):.2f}"
            )
        else:
            shabad["enrichment_status"] = "banidb_unmatched"
            print("✗ No match found")

        # Save progress every 20 shabads
        if (i + 1) % 20 == 0:
            save_enriched(shabads, keertanis)
            print(f"  [Progress saved]")

    matcher.close()
    save_enriched(shabads, keertanis)

    matched = sum(1 for s in shabads if s.get("banidb_shabad_id"))
    print(f"\nPhase 1 complete: {matched}/{len(shabads)} matched via BaniDB")

    # Try Claude disambiguation for unmatched
    unmatched = [s for s in shabads if not s.get("banidb_shabad_id")]
    if unmatched:
        print(f"\n{len(unmatched)} shabads unmatched. These may be Dasam Bani or require manual review.")
        for s in unmatched:
            print(f"  - {s['title']}")


def phase2_themes(shabads, keertanis):
    """Extract themes for all enriched shabads using Claude."""
    enricher = ClaudeEnricher()

    # Get shabads that have translations but no themes yet
    needs_themes = [
        s for s in shabads
        if s.get("english_translation") and not s.get("primary_theme")
    ]

    print(f"Shabads needing theme extraction: {len(needs_themes)}")
    if not needs_themes:
        print("All themes already extracted.")
        return

    batch_size = 12
    for batch_start in range(0, len(needs_themes), batch_size):
        batch = needs_themes[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(needs_themes) + batch_size - 1) // batch_size
        print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} shabads)...")

        themes = enricher.extract_themes_batch(batch)

        for shabad, theme_data in zip(batch, themes):
            if theme_data and isinstance(theme_data, dict):
                shabad["primary_theme"] = theme_data.get("primary_theme")
                shabad["secondary_themes"] = theme_data.get("secondary_themes", [])
                shabad["occasions"] = theme_data.get("occasions", [])
                shabad["mood"] = theme_data.get("mood")
                shabad["brief_meaning"] = theme_data.get("brief_meaning")
                shabad["enrichment_status"] = "complete"
            else:
                print(f"  Warning: No theme data for \"{shabad['title']}\"")

        save_enriched(shabads, keertanis)
        print(f"  [Batch {batch_num} saved]")

    enriched = sum(1 for s in shabads if s["enrichment_status"] == "complete")
    print(f"\nPhase 2 complete: {enriched}/{len(shabads)} fully enriched")


if __name__ == "__main__":
    run_enrichment()
