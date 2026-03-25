"""Dual-model tag validation: Qwen 3 14B + DeepSeek R1 14B.

For each shabad, both models:
1. Score existing tags (1-5 relevance)
2. Suggest missing tags from the vocabulary

Consensus rules:
- Both agree weak (<=2): remove tag
- Both agree strong (>=4): keep tag
- Both suggest same missing tag: add it
- Disagreements: flag for review

Runs sequentially (not simultaneously) to fit in 24GB RAM.
Saves progress every 50 shabads.
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

PROGRESS_PATH = os.path.join(config.DATA_DIR, "tag_validation_progress.json")
REPORT_PATH = os.path.join(config.DATA_DIR, "tag_validation_report.json")


def score_tags_with_model(model_name, shabads, tag_vocab, batch_size=5):
    """Score existing tags and suggest missing ones using a specific model."""
    import ollama

    client = ollama.Client(host=config.OLLAMA_BASE_URL)
    results = {}  # {banidb_id: {scores: {tag: score}, suggested: [tags]}}

    # Build compact tag list for the prompt
    all_tags = sorted(tag_vocab.keys())
    tag_list_str = ", ".join(all_tags[:100])  # Top 100 tags for prompt size

    total = len(shabads)
    for i in range(0, total, batch_size):
        batch = shabads[i : i + batch_size]
        if i % 50 == 0:
            print(f"  [{model_name}] {i}/{total}...")

        for s in batch:
            sid = str(s["banidb_shabad_id"])
            current_tags = s.get("tags", [])
            if not current_tags:
                results[sid] = {"scores": {}, "suggested": []}
                continue

            summary = s.get("brief_meaning", "")
            translation = (s.get("english_translation") or "")[:300]
            theme = s.get("primary_theme", "")
            mood = s.get("mood", "")

            tags_str = ", ".join(current_tags)

            prompt = f"""You are a Sikh Gurbani scholar validating thematic tags for a shabad.

SHABAD CONTEXT:
- Theme: {theme}
- Mood: {mood}
- Summary: {summary}
- Translation excerpt: {translation}

CURRENT TAGS: {tags_str}

TASK 1: Rate each current tag's relevance to this shabad (1=irrelevant, 5=perfect match).
TASK 2: From this vocabulary, suggest up to 3 MISSING tags that strongly apply: {tag_list_str}

Return JSON: {{"scores": {{"tag_name": score, ...}}, "suggested": ["tag1", "tag2"]}}"""

            try:
                # Use chat API with think=False for Qwen, or raw generate for DeepSeek
                if "deepseek" in model_name.lower():
                    # DeepSeek R1 uses thinking tokens — need higher num_predict
                    response = client.chat(
                        model=model_name,
                        messages=[{"role": "user", "content": prompt}],
                        format="json",
                        options={"num_predict": 2000},
                    )
                    text = response.message.content.strip()
                else:
                    response = client.chat(
                        model=model_name,
                        messages=[{"role": "user", "content": prompt}],
                        format="json",
                        options={"num_predict": 500},
                        think=False,
                    )
                    text = response.message.content.strip()

                data = json.loads(text)
                results[sid] = {
                    "scores": data.get("scores", {}),
                    "suggested": data.get("suggested", []),
                }
            except Exception as e:
                # Fallback: keep existing tags with neutral scores
                results[sid] = {
                    "scores": {t: 3 for t in current_tags},
                    "suggested": [],
                    "error": str(e)[:100],
                }

        # Save progress periodically
        if i % 50 == 0 and i > 0:
            save_progress(model_name, results, i, total)

    return results


def save_progress(model_name, results, current, total):
    """Save intermediate progress."""
    progress = {}
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH) as f:
            progress = json.load(f)
    progress[model_name] = {
        "results": results,
        "progress": f"{current}/{total}",
        "timestamp": time.time(),
    }
    with open(PROGRESS_PATH, "w") as f:
        json.dump(progress, f)
    print(f"    [saved progress: {current}/{total}]")


def load_progress(model_name):
    """Load previously saved progress."""
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH) as f:
            progress = json.load(f)
        if model_name in progress:
            return progress[model_name].get("results", {})
    return None


def merge_results(qwen_results, deepseek_results, shabads, tag_vocab):
    """Apply consensus rules to merge dual-model results."""
    report = {
        "removed": [],      # Tags removed (both weak)
        "added": [],        # Tags added (both suggested)
        "disagreements": [], # Flagged for review
        "stats": {"total": 0, "kept": 0, "removed": 0, "added": 0, "flagged": 0},
    }

    valid_tags = set(tag_vocab.keys())
    shabads_by_id = {str(s["banidb_shabad_id"]): s for s in shabads}

    for sid, s in shabads_by_id.items():
        current_tags = list(s.get("tags", []))
        if not current_tags:
            continue

        q = qwen_results.get(sid, {})
        d = deepseek_results.get(sid, {})
        q_scores = q.get("scores", {})
        d_scores = d.get("scores", {})
        q_suggested = set(q.get("suggested", []))
        d_suggested = set(d.get("suggested", []))

        new_tags = []
        for tag in current_tags:
            qs = q_scores.get(tag, 3)  # default neutral
            ds = d_scores.get(tag, 3)

            # Normalize scores to int
            try:
                qs = int(qs)
            except (ValueError, TypeError):
                qs = 3
            try:
                ds = int(ds)
            except (ValueError, TypeError):
                ds = 3

            report["stats"]["total"] += 1

            if qs <= 2 and ds <= 2:
                # Both agree weak — remove
                report["removed"].append({"shabad": sid, "tag": tag, "qwen": qs, "deepseek": ds})
                report["stats"]["removed"] += 1
            elif abs(qs - ds) >= 3:
                # Strong disagreement — flag but keep
                report["disagreements"].append({"shabad": sid, "tag": tag, "qwen": qs, "deepseek": ds})
                report["stats"]["flagged"] += 1
                new_tags.append(tag)
            else:
                # Keep
                new_tags.append(tag)
                report["stats"]["kept"] += 1

        # Add tags both models suggest (if in vocabulary)
        both_suggest = (q_suggested & d_suggested) & valid_tags
        # Don't add tags that are already present
        both_suggest -= set(new_tags)
        for tag in both_suggest:
            new_tags.append(tag)
            report["added"].append({"shabad": sid, "tag": tag})
            report["stats"]["added"] += 1

        s["tags"] = new_tags

    return report


def main():
    print("=" * 60)
    print("  Dual-Model Tag Validation")
    print("=" * 60)

    # Load data
    with open(config.SGGS_DATA_PATH, encoding="utf-8") as f:
        shabads = json.load(f)

    tag_vocab_path = os.path.join(config.DATA_DIR, "tag_vocabulary.json")
    with open(tag_vocab_path, encoding="utf-8") as f:
        vocab_data = json.load(f)
    tag_vocab = {**vocab_data.get("theme_tags", {}), **vocab_data.get("mood_tags", {})}

    tagged = [s for s in shabads if s.get("tags")]
    print(f"Tagged shabads: {len(tagged)}")
    print(f"Tag vocabulary: {len(tag_vocab)} tags")

    # Phase A: Qwen scoring
    print(f"\n{'='*40}")
    print("  Phase A: Qwen 3 14B scoring")
    print(f"{'='*40}")

    qwen_results = load_progress("qwen3:14b")
    if qwen_results and len(qwen_results) >= len(tagged) * 0.9:
        print(f"  Loaded cached results ({len(qwen_results)} shabads)")
    else:
        qwen_results = score_tags_with_model("qwen3:14b", tagged, tag_vocab)
        save_progress("qwen3:14b", qwen_results, len(tagged), len(tagged))

    print(f"  Qwen scored: {len(qwen_results)} shabads")

    # Phase B: DeepSeek R1 scoring
    print(f"\n{'='*40}")
    print("  Phase B: DeepSeek R1 14B scoring")
    print(f"{'='*40}")

    deepseek_results = load_progress("deepseek-r1:14b")
    if deepseek_results and len(deepseek_results) >= len(tagged) * 0.9:
        print(f"  Loaded cached results ({len(deepseek_results)} shabads)")
    else:
        deepseek_results = score_tags_with_model("deepseek-r1:14b", tagged, tag_vocab)
        save_progress("deepseek-r1:14b", deepseek_results, len(tagged), len(tagged))

    print(f"  DeepSeek scored: {len(deepseek_results)} shabads")

    # Phase C: Merge
    print(f"\n{'='*40}")
    print("  Phase C: Consensus merge")
    print(f"{'='*40}")

    report = merge_results(qwen_results, deepseek_results, shabads, tag_vocab)

    print(f"  Total tags evaluated: {report['stats']['total']}")
    print(f"  Kept (consensus): {report['stats']['kept']}")
    print(f"  Removed (both weak): {report['stats']['removed']}")
    print(f"  Added (both suggested): {report['stats']['added']}")
    print(f"  Flagged (disagreement): {report['stats']['flagged']}")

    # Save updated shabads
    with open(config.SGGS_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(shabads, f, ensure_ascii=False, indent=2)
    print(f"\n  Updated {config.SGGS_DATA_PATH}")

    # Save report
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  Report: {REPORT_PATH}")

    # Show sample removals and additions
    if report["removed"]:
        print(f"\n  Sample removals (first 10):")
        for r in report["removed"][:10]:
            print(f"    Shabad {r['shabad']}: removed '{r['tag']}' (Q={r['qwen']}, D={r['deepseek']})")

    if report["added"]:
        print(f"\n  Sample additions (first 10):")
        for a in report["added"][:10]:
            print(f"    Shabad {a['shabad']}: added '{a['tag']}'")


if __name__ == "__main__":
    main()
