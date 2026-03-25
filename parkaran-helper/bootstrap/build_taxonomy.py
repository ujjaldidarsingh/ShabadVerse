"""Build a controlled tag vocabulary from SGGS enriched themes.

Uses Claude Opus 4.6 as primary, Qwen 3 14B as validator.
Clusters 3,108+ unique theme strings into canonical Gurbani-native tags.
"""

import sys
import os
import json
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

import anthropic
from llm.ollama_client import OllamaClient


TAXONOMY_PATH = os.path.join(config.DATA_DIR, "tag_vocabulary.json")

CLUSTERING_PROMPT = """You are a Sikh Gurbani scholar building a thematic taxonomy of Sri Guru Granth Sahib Ji.

Below are {count} unique theme labels extracted from SGGS shabads. Many are synonyms or near-synonyms written differently by an AI (e.g., "Surrender to Waheguru", "Surrender to the Divine", "Surrender to the Lord" are all the same concept).

Your task: Group these into **canonical tags**. Rules:
1. Use Gurbani-native terminology where a well-known term exists (Naam Simran, Hukam, Maya, Birha, Chardi Kala, Bhaanaa, Anand, Seva, Sangat, etc.)
2. For concepts without a single Gurbani term, use clear English (e.g., "Divine Omnipresence", "Impermanence of Life")
3. Don't artificially limit the number of tags - if a theme is genuinely distinct, give it its own tag
4. Each raw theme should map to exactly ONE canonical tag
5. Include a short description and Gurbani term (if applicable) for each tag

Themes to cluster:
{themes}

Return JSON with structure:
{{
  "tags": {{
    "TagName": {{
      "description": "Brief description",
      "gurbani_term": "Punjabi/Gurmukhi term if applicable, or empty string",
      "raw_themes": ["list", "of", "raw", "theme", "strings", "that", "map", "here"]
    }}
  }}
}}"""


def load_themes():
    """Load all unique themes and moods from SGGS data."""
    sggs_path = config.SGGS_DATA_PATH
    with open(sggs_path, encoding="utf-8") as f:
        shabads = json.load(f)

    themes = Counter()
    moods = Counter()
    for s in shabads:
        if s.get("primary_theme"):
            themes[s["primary_theme"]] += 1
        if s.get("mood"):
            moods[s["mood"]] += 1

    return themes, moods


def cluster_with_opus(themes_list, batch_size=80):
    """Use Claude Opus to cluster themes into canonical tags."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    all_tags = {}

    total_batches = (len(themes_list) + batch_size - 1) // batch_size
    for i in range(0, len(themes_list), batch_size):
        batch = themes_list[i : i + batch_size]
        batch_num = i // batch_size + 1
        print(f"  Opus batch {batch_num}/{total_batches} ({len(batch)} themes)...", end=" ", flush=True)

        themes_text = "\n".join(f"- {t}" for t in batch)
        prompt = CLUSTERING_PROMPT.format(count=len(batch), themes=themes_text)

        for attempt in range(3):
            try:
                response = client.messages.create(
                    model="claude-opus-4-20250514",
                    max_tokens=4000,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()
                # Strip markdown fences
                if text.startswith("```"):
                    text = text.split("\n", 1)[1]
                    if text.endswith("```"):
                        text = text[: text.rfind("```")]
                    text = text.strip()

                result = json.loads(text)
                batch_tags = result.get("tags", {})

                # Merge into all_tags
                for tag_name, tag_data in batch_tags.items():
                    if tag_name in all_tags:
                        # Merge raw_themes
                        existing = set(all_tags[tag_name].get("raw_themes", []))
                        existing.update(tag_data.get("raw_themes", []))
                        all_tags[tag_name]["raw_themes"] = list(existing)
                    else:
                        all_tags[tag_name] = tag_data

                print(f"done ({len(batch_tags)} tags)")
                break
            except json.JSONDecodeError:
                print(f"JSON error, retrying...", end=" ")
                time.sleep(2)
            except Exception as e:
                print(f"error: {e}, retrying...", end=" ")
                time.sleep(5)
        else:
            print("failed after 3 attempts")

        time.sleep(1)  # Rate limiting

    return all_tags


def validate_with_qwen(opus_tags, themes_list):
    """Use Qwen to validate Opus clustering. Returns disagreements."""
    llm = OllamaClient()
    if not llm.is_available():
        print("  Qwen not available, skipping validation.")
        return {}

    # Build reverse mapping: raw_theme -> opus_tag
    opus_mapping = {}
    for tag_name, tag_data in opus_tags.items():
        for raw in tag_data.get("raw_themes", []):
            opus_mapping[raw] = tag_name

    # Sample 200 themes for validation (not all - too slow)
    import random
    random.seed(42)
    sample = random.sample(themes_list, min(200, len(themes_list)))

    print(f"  Validating {len(sample)} themes with Qwen...")
    disagreements = {}

    batch_size = 20
    for i in range(0, len(sample), batch_size):
        batch = sample[i : i + batch_size]
        tag_names = list(opus_tags.keys())

        prompt = f"""Given these canonical Gurbani tags: {', '.join(tag_names[:100])}

For each theme below, assign the BEST matching canonical tag:
{chr(10).join(f'{j+1}. {t}' for j, t in enumerate(batch))}

Return JSON: {{"assignments": [{{"theme": "...", "tag": "..."}}]}}"""

        try:
            result = llm.generate_json(prompt, max_tokens=2000)
            assignments = result.get("assignments", [])
            for a in assignments:
                theme = a.get("theme", "")
                qwen_tag = a.get("tag", "")
                opus_tag = opus_mapping.get(theme, "")
                if opus_tag and qwen_tag and opus_tag != qwen_tag:
                    disagreements[theme] = {
                        "opus": opus_tag,
                        "qwen": qwen_tag,
                    }
        except Exception:
            pass

    print(f"  Disagreements: {len(disagreements)}/{len(sample)} ({len(disagreements)*100//max(1,len(sample))}%)")
    return disagreements


def build_taxonomy():
    """Main entry point: build tag vocabulary."""
    print("=" * 60)
    print("  Building SGGS Theme Taxonomy")
    print("=" * 60)

    # Load themes
    themes, moods = load_themes()
    print(f"\nUnique themes: {len(themes)}")
    print(f"Unique moods: {len(moods)}")

    themes_list = list(themes.keys())
    moods_list = list(moods.keys())

    # Cluster themes with Opus
    print(f"\nClustering {len(themes_list)} themes with Opus 4.6...")
    opus_tags = cluster_with_opus(themes_list)
    print(f"Opus produced {len(opus_tags)} canonical tags.")

    # Also cluster moods (smaller set, one batch)
    print(f"\nClustering {len(moods_list)} moods with Opus 4.6...")
    mood_tags = cluster_with_opus(moods_list, batch_size=200)
    print(f"Opus produced {len(mood_tags)} mood tags.")

    # Validate with Qwen
    print("\nValidating with Qwen 3 14B...")
    disagreements = validate_with_qwen(opus_tags, themes_list)

    # Build the vocabulary
    vocabulary = {
        "version": "1.0",
        "stats": {
            "total_raw_themes": len(themes_list),
            "total_raw_moods": len(moods_list),
            "canonical_theme_tags": len(opus_tags),
            "canonical_mood_tags": len(mood_tags),
            "qwen_disagreements": len(disagreements),
        },
        "theme_tags": opus_tags,
        "mood_tags": mood_tags,
        "disagreements": disagreements,
    }

    # Save
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(TAXONOMY_PATH, "w", encoding="utf-8") as f:
        json.dump(vocabulary, f, ensure_ascii=False, indent=2)

    print(f"\nSaved taxonomy to {TAXONOMY_PATH}")
    print(f"  Theme tags: {len(opus_tags)}")
    print(f"  Mood tags: {len(mood_tags)}")
    print(f"  Disagreements to review: {len(disagreements)}")

    # Print top tags by coverage
    print("\nTop 20 theme tags by coverage:")
    tag_counts = []
    for tag_name, tag_data in opus_tags.items():
        raw_count = len(tag_data.get("raw_themes", []))
        # Count how many shabads these raw themes cover
        shabad_count = sum(themes.get(rt, 0) for rt in tag_data.get("raw_themes", []))
        tag_counts.append((tag_name, shabad_count, raw_count))
    tag_counts.sort(key=lambda x: x[1], reverse=True)
    for tag_name, shabad_count, raw_count in tag_counts[:20]:
        gterm = opus_tags[tag_name].get("gurbani_term", "")
        print(f"  {shabad_count:5d} shabads ({raw_count:3d} raw themes) - {tag_name}" + (f" ({gterm})" if gterm else ""))


if __name__ == "__main__":
    build_taxonomy()
