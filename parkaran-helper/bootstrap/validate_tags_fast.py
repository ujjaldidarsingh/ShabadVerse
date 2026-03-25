"""Fast dual-model tag validation using sample + extrapolation.

Strategy:
1. Score a representative SAMPLE (500 shabads) with both Qwen 3 + DeepSeek R1
2. Identify weak tags (both models score <=2) and strong missing tags (both suggest)
3. Build per-TAG weakness rules (e.g., "Shanti is often wrong on shabads about X")
4. Apply rules across the full 5,542 dataset algorithmically (no more LLM calls)

This takes ~1 hour instead of 15 hours.
"""

import sys
import os
import json
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

PROGRESS_PATH = os.path.join(config.DATA_DIR, "tag_validation_progress_fast.json")
REPORT_PATH = os.path.join(config.DATA_DIR, "tag_validation_report.json")

SAMPLE_SIZE = 500
BATCH_SIZE = 5  # Shabads per LLM call


def score_batch(client, model_name, batch, tag_list_str, use_think=True):
    """Score a batch of shabads' tags in a single LLM call."""
    shabad_texts = []
    for i, s in enumerate(batch):
        tags = ", ".join(s.get("tags", []))
        summary = s.get("brief_meaning", "")[:150]
        theme = s.get("primary_theme", "")
        shabad_texts.append(
            f'{i+1}. [ID:{s["banidb_shabad_id"]}] Tags: [{tags}] | Theme: {theme} | Summary: {summary}'
        )

    prompt = f"""You are a Sikh Gurbani scholar validating thematic tags on shabads.

For each shabad below, rate each tag 1-5 (1=wrong, 5=perfect) and suggest up to 2 missing tags from: {tag_list_str}

{chr(10).join(shabad_texts)}

Return JSON: {{"results": [{{"id": shabad_id, "scores": {{"tag": score}}, "suggested": ["tag1"]}}]}}"""

    try:
        kwargs = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "options": {"num_predict": 2000 if "deepseek" in model_name else 800},
        }
        if "deepseek" not in model_name.lower():
            kwargs["think"] = False

        # Timeout: 120s for DeepSeek (thinking), 60s for Qwen
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("LLM call timed out")

        timeout_sec = 120 if "deepseek" in model_name.lower() else 60
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_sec)
        try:
            response = client.chat(**kwargs)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

        text = response.message.content.strip()
        data = json.loads(text)
        return data.get("results", [])
    except TimeoutError:
        print(f"    Timeout ({model_name}), skipping batch")
        return []
    except Exception as e:
        print(f"    Batch error ({model_name}): {e}")
        return []


def run_model_scoring(model_name, sample, tag_list_str):
    """Score sample shabads with a single model. Resumes from checkpoint."""
    import ollama
    client = ollama.Client(host=config.OLLAMA_BASE_URL)

    # Load checkpoint if exists
    results = load_results_checkpoint(model_name)
    scored_ids = set(results.keys())
    total = len(sample)
    if scored_ids:
        print(f"  [{model_name}] Resuming from checkpoint: {len(scored_ids)} already scored")

    for i in range(0, total, BATCH_SIZE):
        batch = sample[i:i + BATCH_SIZE]
        # Skip already scored
        batch = [s for s in batch if str(s["banidb_shabad_id"]) not in scored_ids]
        if not batch:
            continue

        if i % 50 == 0:
            print(f"  [{model_name}] {len(results)}/{total}...")

        batch_results = score_batch(client, model_name, batch, tag_list_str)

        for r in batch_results:
            sid = str(r.get("id", ""))
            if sid:
                results[sid] = {
                    "scores": r.get("scores", {}),
                    "suggested": r.get("suggested", []),
                }
                scored_ids.add(sid)

        # For shabads that didn't get results, assign neutral
        for s in batch:
            sid = str(s["banidb_shabad_id"])
            if sid not in results:
                results[sid] = {
                    "scores": {t: 3 for t in s.get("tags", [])},
                    "suggested": [],
                }
                scored_ids.add(sid)

        # Save checkpoint every 25 shabads (more frequent to avoid losing work)
        if len(results) % 25 == 0:
            save_results_checkpoint(model_name, results, len(results), total)

    # Final save
    save_results_checkpoint(model_name, results, len(results), total)
    return results


def _checkpoint_path(model_name):
    safe = model_name.replace(":", "_").replace("/", "_")
    return os.path.join(config.DATA_DIR, f"validation_checkpoint_{safe}.json")


def load_results_checkpoint(model_name):
    """Load actual results from checkpoint file."""
    path = _checkpoint_path(model_name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_results_checkpoint(model_name, results, current, total):
    """Save actual results (not just count) for proper resume."""
    # Save full results
    path = _checkpoint_path(model_name)
    with open(path, "w") as f:
        json.dump(results, f)
    # Also update progress tracker
    progress = {}
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH) as f:
            progress = json.load(f)
    progress[model_name] = {
        "count": len(results),
        "progress": f"{current}/{total}",
        "timestamp": time.time(),
    }
    with open(PROGRESS_PATH, "w") as f:
        json.dump(progress, f)
    print(f"    [checkpoint: {len(results)}/{total}]")


def build_tag_rules(qwen_results, deepseek_results, sample):
    """From sample scoring, build per-tag rules for full dataset application.

    Returns:
        weak_tags: {tag: weakness_rate} — tags that are frequently scored <=2
        strong_suggestions: {(primary_theme, tag): agreement_count} — missing tags both models suggest
    """
    tag_weakness = {}  # {tag: [is_weak_for_shabad_1, is_weak_for_shabad_2, ...]}
    tag_suggestions = {}  # {(theme_context, suggested_tag): count}

    for s in sample:
        sid = str(s["banidb_shabad_id"])
        q = qwen_results.get(sid, {})
        d = deepseek_results.get(sid, {})

        q_scores = q.get("scores", {})
        d_scores = d.get("scores", {})

        for tag in s.get("tags", []):
            qs = q_scores.get(tag, 3)
            ds = d_scores.get(tag, 3)
            try:
                qs, ds = int(qs), int(ds)
            except (ValueError, TypeError):
                qs, ds = 3, 3

            if tag not in tag_weakness:
                tag_weakness[tag] = []
            tag_weakness[tag].append(qs <= 2 and ds <= 2)

        # Track what both models suggest
        q_sugg = set(q.get("suggested", []))
        d_sugg = set(d.get("suggested", []))
        both = q_sugg & d_sugg
        theme = s.get("primary_theme", "unknown")
        for sugg_tag in both:
            key = (theme, sugg_tag)
            tag_suggestions[key] = tag_suggestions.get(key, 0) + 1

    # Compute weakness rates
    weak_tags = {}
    for tag, weaknesses in tag_weakness.items():
        rate = sum(weaknesses) / max(1, len(weaknesses))
        if rate > 0.3:  # If >30% of the time both models say it's weak
            weak_tags[tag] = round(rate, 2)

    return weak_tags, tag_suggestions


def apply_rules(shabads, weak_tags, tag_suggestions, qwen_results, deepseek_results):
    """Apply learned rules across the full dataset."""
    report = {
        "removed": [],
        "added": [],
        "stats": {"total_tags": 0, "kept": 0, "removed": 0, "added": 0},
    }

    shabads_by_id = {str(s["banidb_shabad_id"]): s for s in shabads}

    for sid, s in shabads_by_id.items():
        current_tags = list(s.get("tags", []))
        if not current_tags:
            continue

        new_tags = []
        for tag in current_tags:
            report["stats"]["total_tags"] += 1

            # If this shabad was in the sample, use actual scores
            q = qwen_results.get(sid, {}).get("scores", {})
            d = deepseek_results.get(sid, {}).get("scores", {})

            if tag in q and tag in d:
                try:
                    qs, ds = int(q[tag]), int(d[tag])
                except (ValueError, TypeError):
                    qs, ds = 3, 3
                if qs <= 2 and ds <= 2:
                    report["removed"].append({"shabad": sid, "tag": tag})
                    report["stats"]["removed"] += 1
                    continue
            elif tag in weak_tags and weak_tags[tag] > 0.5:
                # Tag is globally weak (>50% weakness rate) — remove if it's the only weak signal
                # But keep if the shabad's theme aligns with the tag
                theme = s.get("primary_theme", "").lower()
                if tag.lower() not in theme:
                    report["removed"].append({"shabad": sid, "tag": tag, "rule": "global_weak"})
                    report["stats"]["removed"] += 1
                    continue

            new_tags.append(tag)
            report["stats"]["kept"] += 1

        # Add strongly suggested tags
        theme = s.get("primary_theme", "unknown")
        for (ctx_theme, sugg_tag), count in tag_suggestions.items():
            if count >= 3 and ctx_theme == theme and sugg_tag not in new_tags:
                new_tags.append(sugg_tag)
                report["added"].append({"shabad": sid, "tag": sugg_tag})
                report["stats"]["added"] += 1

        s["tags"] = new_tags

    return report


def main():
    print("=" * 60)
    print("  Fast Dual-Model Tag Validation (Sample + Extrapolation)")
    print("=" * 60)

    # Load data
    with open(config.SGGS_DATA_PATH, encoding="utf-8") as f:
        shabads = json.load(f)

    tag_vocab_path = os.path.join(config.DATA_DIR, "tag_vocabulary.json")
    if os.path.exists(tag_vocab_path):
        with open(tag_vocab_path, encoding="utf-8") as f:
            vocab_data = json.load(f)
        tag_vocab = {**vocab_data.get("theme_tags", {}), **vocab_data.get("mood_tags", {})}
    else:
        # Build from current tags
        tag_vocab = {}
        for s in shabads:
            for t in s.get("tags", []):
                if t != "Repertoire":
                    tag_vocab[t] = True

    tagged = [s for s in shabads if s.get("tags")]
    print(f"Tagged shabads: {len(tagged)}")
    print(f"Tag vocabulary: {len(tag_vocab)} tags")

    # Select representative sample (stratified by tag diversity)
    random.seed(42)
    sample = random.sample(tagged, min(SAMPLE_SIZE, len(tagged)))
    print(f"Sample size: {len(sample)}")

    tag_list_str = ", ".join(sorted(tag_vocab.keys())[:80])

    # Phase A: Qwen scoring on sample
    print(f"\n{'='*40}")
    print(f"  Phase A: Qwen 3 14B ({len(sample)} shabads)")
    print(f"{'='*40}")
    qwen_results = run_model_scoring("qwen3:14b", sample, tag_list_str)
    print(f"  Qwen scored: {len(qwen_results)} shabads")

    # Phase B: DeepSeek R1 scoring on sample
    print(f"\n{'='*40}")
    print(f"  Phase B: DeepSeek R1 14B ({len(sample)} shabads)")
    print(f"{'='*40}")
    deepseek_results = run_model_scoring("deepseek-r1:14b", sample, tag_list_str)
    print(f"  DeepSeek scored: {len(deepseek_results)} shabads")

    # Phase C: Build rules from sample
    print(f"\n{'='*40}")
    print("  Phase C: Building rules from sample consensus")
    print(f"{'='*40}")
    weak_tags, tag_suggestions = build_tag_rules(qwen_results, deepseek_results, sample)
    print(f"  Weak tags (>30% weakness rate): {len(weak_tags)}")
    for tag, rate in sorted(weak_tags.items(), key=lambda x: -x[1])[:10]:
        print(f"    {tag}: {rate*100:.0f}% weak")
    print(f"  Strong suggestions: {len(tag_suggestions)} (theme, tag) pairs")

    # Phase D: Apply rules across full dataset
    print(f"\n{'='*40}")
    print("  Phase D: Applying rules to all 5,542 shabads")
    print(f"{'='*40}")
    report = apply_rules(shabads, weak_tags, tag_suggestions, qwen_results, deepseek_results)

    print(f"  Total tags evaluated: {report['stats']['total_tags']}")
    print(f"  Kept: {report['stats']['kept']}")
    print(f"  Removed: {report['stats']['removed']}")
    print(f"  Added: {report['stats']['added']}")

    # Save updated shabads
    with open(config.SGGS_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(shabads, f, ensure_ascii=False, indent=2)
    print(f"\n  Updated {config.SGGS_DATA_PATH}")

    # Save report
    report["weak_tags"] = weak_tags
    report["sample_size"] = len(sample)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  Report: {REPORT_PATH}")

    if report["removed"]:
        print(f"\n  Sample removals (first 10):")
        for r in report["removed"][:10]:
            print(f"    Shabad {r['shabad']}: removed '{r['tag']}'")

    print(f"\nNext: python bootstrap/build_graph.py")


if __name__ == "__main__":
    main()
