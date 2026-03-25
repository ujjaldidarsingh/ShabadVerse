"""Batch-enrich all SGGS shabads with themes using local LLM.

Extracts primary_theme, mood, and brief_meaning for each shabad.
Resumable - skips shabads that already have themes.
Saves progress every 50 shabads.
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from llm.ollama_client import OllamaClient


def enrich_sggs():
    sggs_path = config.SGGS_DATA_PATH
    if not os.path.exists(sggs_path):
        print(f"SGGS data not found at {sggs_path}")
        print("Run 'python bootstrap/fetch_sggs.py' first.")
        return

    print("Loading SGGS shabads...")
    with open(sggs_path, encoding="utf-8") as f:
        shabads = json.load(f)

    # Filter to those needing enrichment
    to_enrich = [
        s for s in shabads
        if not s.get("primary_theme")
        and s.get("english_translation")
        and len(s["english_translation"]) > 20
    ]

    already_done = len(shabads) - len(to_enrich)
    print(f"Total: {len(shabads)}, Already enriched: {already_done}, To enrich: {len(to_enrich)}")

    if not to_enrich:
        print("All shabads already enriched!")
        return

    llm = OllamaClient()
    if not llm.is_available():
        print(f"Ollama not available. Start Ollama and ensure '{config.OLLAMA_MODEL}' is pulled.")
        return

    print(f"Using model: {config.OLLAMA_MODEL}")
    print(f"Estimated time: ~{len(to_enrich) * 3 // 60} minutes\n")

    batch_size = 5
    enriched_count = 0
    failed_count = 0

    for i in range(0, len(to_enrich), batch_size):
        batch = to_enrich[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(to_enrich) + batch_size - 1) // batch_size

        print(f"  Batch {batch_num}/{total_batches} ({enriched_count + already_done}/{len(shabads)} total)...", end=" ", flush=True)

        # Build prompt for this batch
        shabad_texts = []
        for j, s in enumerate(batch):
            text = f"{j + 1}. Translation: {s['english_translation'][:400]}"
            if s.get("rahao_english"):
                text += f"\n   Rahao (core verse): {s['rahao_english'][:200]}"
            shabad_texts.append(text)

        prompt = f"""For each Sikh Gurbani shabad below, extract:
- "primary_theme": Main spiritual theme (e.g., "Surrender to Waheguru", "Detachment from Maya", "Divine love")
- "mood": Spiritual mood (e.g., "Devotional longing", "Joyful praise", "Contemplative peace")
- "brief_meaning": One sentence summary

{chr(10).join(shabad_texts)}

Return a JSON object with key "results" containing an array of {len(batch)} objects in order."""

        try:
            result = llm.generate_json(prompt, max_tokens=2000)
            themes = result.get("results", result) if isinstance(result, dict) else result

            if isinstance(themes, list) and len(themes) >= len(batch):
                for j, s in enumerate(batch):
                    if themes[j] and isinstance(themes[j], dict):
                        s["primary_theme"] = themes[j].get("primary_theme", "")
                        s["mood"] = themes[j].get("mood", "")
                        s["brief_meaning"] = themes[j].get("brief_meaning", "")
                        enriched_count += 1
                    else:
                        failed_count += 1
                print("done")
            else:
                # Partial or bad response - try individual
                print(f"bad batch response, trying individually...")
                for s in batch:
                    try:
                        single_prompt = f"""For this Sikh Gurbani shabad, extract primary_theme, mood, and brief_meaning.

Translation: {s['english_translation'][:400]}

Return JSON with keys: "primary_theme", "mood", "brief_meaning"."""
                        single_result = llm.generate_json(single_prompt, max_tokens=500)
                        if isinstance(single_result, dict) and single_result.get("primary_theme"):
                            s["primary_theme"] = single_result["primary_theme"]
                            s["mood"] = single_result.get("mood", "")
                            s["brief_meaning"] = single_result.get("brief_meaning", "")
                            enriched_count += 1
                        else:
                            failed_count += 1
                    except Exception:
                        failed_count += 1

        except Exception as e:
            print(f"error: {e}")
            failed_count += len(batch)

        # Save progress every 50 shabads
        if enriched_count > 0 and enriched_count % 50 < batch_size:
            with open(sggs_path, "w", encoding="utf-8") as f:
                json.dump(shabads, f, ensure_ascii=False, indent=2)
            print(f"    [saved progress: {enriched_count + already_done}/{len(shabads)}]")

    # Final save
    with open(sggs_path, "w", encoding="utf-8") as f:
        json.dump(shabads, f, ensure_ascii=False, indent=2)

    total_enriched = already_done + enriched_count
    print(f"\nDone! Enriched: {total_enriched}/{len(shabads)}, Failed: {failed_count}")
    print(f"Now run: python bootstrap/embed_sggs.py")


if __name__ == "__main__":
    enrich_sggs()
