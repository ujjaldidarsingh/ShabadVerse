"""Apply canonical tags to all SGGS and personal library shabads.

Uses the tag vocabulary from build_taxonomy.py.
Strategy: alias lookup first (fast), then Opus for unmatched, Qwen validates.
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

import anthropic
from llm.ollama_client import OllamaClient

TAXONOMY_PATH = os.path.join(config.DATA_DIR, "tag_vocabulary.json")


def load_taxonomy():
    """Load the tag vocabulary."""
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        return json.load(f)


def build_alias_map(taxonomy):
    """Build reverse mapping: raw_theme_string -> list of canonical tags."""
    alias_map = {}
    for tag_name, tag_data in taxonomy.get("theme_tags", {}).items():
        for raw in tag_data.get("raw_themes", []):
            raw_lower = raw.lower().strip()
            if raw_lower not in alias_map:
                alias_map[raw_lower] = []
            alias_map[raw_lower].append(tag_name)
    return alias_map


def build_mood_map(taxonomy):
    """Build reverse mapping: raw_mood_string -> canonical mood tag."""
    mood_map = {}
    for tag_name, tag_data in taxonomy.get("mood_tags", {}).items():
        for raw in tag_data.get("raw_themes", []):
            mood_map[raw.lower().strip()] = tag_name
    return mood_map


def tag_via_alias(shabad, alias_map, mood_map):
    """Try to assign tags via alias lookup. Returns tags list or None if no match."""
    tags = set()

    # Match primary_theme
    theme = (shabad.get("primary_theme") or "").lower().strip()
    if theme in alias_map:
        tags.update(alias_map[theme])

    # Match mood as a tag too
    mood = (shabad.get("mood") or "").lower().strip()
    if mood in mood_map:
        tags.add(mood_map[mood])

    return list(tags) if tags else None


def tag_with_opus(shabads_batch, tag_names, client):
    """Use Opus to assign tags to shabads that alias lookup missed."""
    shabad_texts = []
    for i, s in enumerate(shabads_batch):
        text = f"{i+1}. Theme: {s.get('primary_theme','N/A')} | Mood: {s.get('mood','N/A')}"
        if s.get("brief_meaning"):
            text += f" | {s['brief_meaning'][:100]}"
        if s.get("english_translation"):
            text += f" | Translation: {s['english_translation'][:200]}"
        shabad_texts.append(text)

    prompt = f"""You are tagging Sikh Gurbani shabads from a controlled vocabulary.

Available tags: {', '.join(tag_names[:200])}

For each shabad below, assign ALL applicable tags (typically 2-6). Don't limit yourself - if a shabad genuinely covers many topics, tag them all.

{chr(10).join(shabad_texts)}

Return JSON: {{"results": [{{"index": 1, "tags": ["Tag1", "Tag2", ...]}}]}}"""

    try:
        response = client.messages.create(
            model="claude-opus-4-20250514",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[: text.rfind("```")]
            text = text.strip()
        result = json.loads(text)
        return result.get("results", [])
    except Exception as e:
        print(f"    Opus error: {e}")
        return []


def tag_with_qwen(shabads_batch, tag_names, llm):
    """Use Qwen to assign tags (for validation)."""
    shabad_texts = []
    for i, s in enumerate(shabads_batch):
        text = f"{i+1}. Theme: {s.get('primary_theme','N/A')} | Mood: {s.get('mood','N/A')}"
        if s.get("brief_meaning"):
            text += f" | {s['brief_meaning'][:100]}"
        shabad_texts.append(text)

    prompt = f"""Tag these Gurbani shabads from this vocabulary: {', '.join(tag_names[:150])}

{chr(10).join(shabad_texts)}

Return JSON: {{"results": [{{"index": 1, "tags": ["Tag1", "Tag2"]}}]}}"""

    try:
        result = llm.generate_json(prompt, max_tokens=2000)
        return result.get("results", [])
    except Exception:
        return []


def tag_all_shabads():
    """Main entry point: tag all shabads."""
    print("=" * 60)
    print("  Tagging All SGGS Shabads")
    print("=" * 60)

    taxonomy = load_taxonomy()
    alias_map = build_alias_map(taxonomy)
    mood_map = build_mood_map(taxonomy)
    tag_names = list(taxonomy.get("theme_tags", {}).keys())
    print(f"Tag vocabulary: {len(tag_names)} theme tags, {len(taxonomy.get('mood_tags', {}))} mood tags")
    print(f"Alias map entries: {len(alias_map)}")

    # Load SGGS shabads
    with open(config.SGGS_DATA_PATH, encoding="utf-8") as f:
        sggs_shabads = json.load(f)

    # Phase 1: Alias lookup (fast)
    print(f"\nPhase 1: Alias lookup on {len(sggs_shabads)} SGGS shabads...")
    alias_matched = 0
    unmatched = []
    for s in sggs_shabads:
        if s.get("tags"):  # Already tagged (resumable)
            alias_matched += 1
            continue
        tags = tag_via_alias(s, alias_map, mood_map)
        if tags:
            s["tags"] = tags
            s["tags_source"] = "alias"
            alias_matched += 1
        else:
            unmatched.append(s)
    print(f"  Alias matched: {alias_matched}, Unmatched: {len(unmatched)}")

    # Phase 2: Opus for unmatched
    if unmatched:
        print(f"\nPhase 2: Opus tagging for {len(unmatched)} unmatched shabads...")
        opus_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        batch_size = 15

        for i in range(0, len(unmatched), batch_size):
            batch = unmatched[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(unmatched) + batch_size - 1) // batch_size
            print(f"  Opus batch {batch_num}/{total_batches}...", end=" ", flush=True)

            results = tag_with_opus(batch, tag_names, opus_client)

            for r in results:
                idx = r.get("index", 0) - 1
                if 0 <= idx < len(batch) and r.get("tags"):
                    # Validate tags against vocabulary
                    valid_tags = [t for t in r["tags"] if t in tag_names or t in taxonomy.get("mood_tags", {})]
                    if valid_tags:
                        batch[idx]["tags"] = valid_tags
                        batch[idx]["tags_source"] = "opus"

            print("done")
            time.sleep(0.5)

            # Save progress every 100
            if i > 0 and i % 100 < batch_size:
                with open(config.SGGS_DATA_PATH, "w", encoding="utf-8") as f:
                    json.dump(sggs_shabads, f, ensure_ascii=False, indent=2)

    # Phase 3: Qwen validation on a sample
    llm = OllamaClient()
    if llm.is_available():
        import random
        random.seed(42)
        tagged = [s for s in sggs_shabads if s.get("tags")]
        sample = random.sample(tagged, min(100, len(tagged)))
        print(f"\nPhase 3: Qwen validation on {len(sample)} sample shabads...")

        batch_size = 10
        disagreements = 0
        for i in range(0, len(sample), batch_size):
            batch = sample[i : i + batch_size]
            qwen_results = tag_with_qwen(batch, tag_names, llm)
            for j, r in enumerate(qwen_results):
                if j < len(batch) and r.get("tags"):
                    opus_tags = set(batch[j].get("tags", []))
                    qwen_tags = set(r["tags"])
                    if opus_tags != qwen_tags:
                        # Only count strong disagreements (no overlap)
                        if not opus_tags & qwen_tags:
                            disagreements += 1

        print(f"  Strong disagreements: {disagreements}/{len(sample)}")
    else:
        print("\nSkipping Qwen validation (not available)")

    # Final save
    with open(config.SGGS_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(sggs_shabads, f, ensure_ascii=False, indent=2)

    # Stats
    tagged_count = sum(1 for s in sggs_shabads if s.get("tags"))
    avg_tags = sum(len(s.get("tags", [])) for s in sggs_shabads if s.get("tags")) / max(1, tagged_count)
    print(f"\nDone! Tagged: {tagged_count}/{len(sggs_shabads)} ({tagged_count*100//len(sggs_shabads)}%)")
    print(f"Average tags per shabad: {avg_tags:.1f}")

    # Also tag personal library
    print("\nTagging personal library...")
    enriched_path = config.ENRICHED_DATA_PATH
    if os.path.exists(enriched_path):
        with open(enriched_path, encoding="utf-8") as f:
            data = json.load(f)
        personal_shabads = data.get("shabads", data) if isinstance(data, dict) else data
        tagged_personal = 0
        for s in personal_shabads:
            tags = tag_via_alias(s, alias_map, mood_map)
            if tags:
                s["tags"] = tags
                tagged_personal += 1
        with open(enriched_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  Tagged: {tagged_personal}/{len(personal_shabads)} personal shabads")

    print("\nNext: python bootstrap/build_graph.py")


if __name__ == "__main__":
    tag_all_shabads()
