"""Clean display_gurmukhi in sggs_all_shabads.json and similarity_graph.json.

Fixes two issues:
1. Trailing Gurmukhi line numbers (੧, ੨, etc.) on 2,392 shabads
2. Generic 'ੴ ਸਤਿਗੁਰ ਪ੍ਰਸਾਦਿ ॥' display names (16 shabads) - replaced with
   the actual first content line
"""

import json
import os
import sys

GURMUKHI_DIGITS = "੦੧੨੩੪੫੬੭੮੯"

# Lines that are structural markers, not content
SKIP_LINES = {
    "ੴ ਸਤਿਗੁਰ ਪ੍ਰਸਾਦਿ ॥",
    "ੴ ਸਤਿਗੁਰ ਪ੍ਰਸਾਦਿ ।।",
    "॥",
    "ਸਲੋਕੁ ॥",
    "ਸਲੋਕ ॥",
    "ਪਉੜੀ ॥",
    "ਡਖਣਾ ॥",
    "ਡਖਣੇ ॥",
    "ਛੰਤ ॥",
}


def strip_trailing_digits(text):
    """Remove trailing BaniDB verse line numbers from display text.

    Handles two patterns:
    1. Trailing digit: 'ਕੇਵਡੁ ਚੀਰਾ ੧' -> 'ਕੇਵਡੁ ਚੀਰਾ'
    2. Pipe-wrapped digit: 'ਬਲਿ ਜਾਉ ॥੧॥' -> 'ਬਲਿ ਜਾਉ'

    Only strips when the preceding body has enough content (>5 chars)
    to avoid mangling 'ਮਃ ੫ ॥' style headings.
    """
    import re

    t = text.strip()

    # Pattern 2: strip trailing ॥digit(s)॥ (e.g. ॥੧॥, ॥੨੮॥)
    match = re.search(r"\s*॥[" + GURMUKHI_DIGITS + r"]+॥\s*$", t)
    if match and match.start() > 5:
        t = t[: match.start()].rstrip()

    # Pattern 1: strip trailing standalone digit(s)
    core = t.rstrip(" ॥").rstrip()
    parts = core.rsplit(None, 1)
    if len(parts) == 2:
        body, last = parts
        if all(c in GURMUKHI_DIGITS for c in last) and len(body) > 5:
            return body.rstrip(" ॥").rstrip()
    return t


def is_heading_line(line):
    """Detect raag/form heading lines (not shabad content)."""
    clean = line.strip().rstrip(" ॥").rstrip()
    if clean in SKIP_LINES:
        return True
    # Short lines with raag/mehla markers
    heading_words = {"ਰਾਗੁ", "ਰਾਗ", "ਮਹਲਾ", "ਮਃ", "ਘਰੁ", "ਵਾਰ", "ਕੀ", "ਕੇ"}
    words = clean.split()
    if len(clean) < 50 and any(w in heading_words for w in words[:6]):
        return True
    return False


def find_first_content_line(gurmukhi_text):
    """Find the first actual content line, skipping invocations and headings."""
    if not gurmukhi_text:
        return ""
    for line in gurmukhi_text.split("\n"):
        clean = line.strip()
        if not clean:
            continue
        if clean in SKIP_LINES:
            continue
        if any(clean.startswith(prefix) for prefix in ["ੴ "]):
            continue
        if is_heading_line(clean):
            continue
        return strip_trailing_digits(clean)
    return ""


def main():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")

    # Load SGGS data
    sggs_path = os.path.join(data_dir, "sggs_all_shabads.json")
    with open(sggs_path) as f:
        sggs = json.load(f)

    # Load graph
    graph_path = os.path.join(data_dir, "similarity_graph.json")
    with open(graph_path) as f:
        graph = json.load(f)

    meta = graph.get("metadata", {})

    # Build lookup for quick access
    sggs_lookup = {s["banidb_shabad_id"]: s for s in sggs}

    digit_fixed = 0
    invocation_fixed = 0
    unchanged = 0

    for s in sggs:
        sid = s["banidb_shabad_id"]
        display = s.get("display_gurmukhi", "")
        original = display

        # Fix 1: Replace generic invocation displays
        if display.strip() in SKIP_LINES or display.strip().startswith("ੴ ") and len(display.strip()) < 30:
            content_line = find_first_content_line(s.get("gurmukhi_text", ""))
            if content_line:
                display = content_line
                invocation_fixed += 1

        # Fix 2: Strip trailing line numbers
        cleaned = strip_trailing_digits(display)
        if cleaned != display:
            display = cleaned
            digit_fixed += 1

        if display != original:
            s["display_gurmukhi"] = display

            # Also update graph metadata
            sid_str = str(sid)
            if sid_str in meta:
                meta[sid_str]["gurmukhi"] = display

    # Save SGGS
    with open(sggs_path, "w") as f:
        json.dump(sggs, f, ensure_ascii=False, indent=2)

    # Save graph
    with open(graph_path, "w") as f:
        json.dump(graph, f, ensure_ascii=False)

    total = len(sggs)
    print(f"Audit complete: {total} shabads")
    print(f"  Invocation display fixed: {invocation_fixed}")
    print(f"  Trailing digits stripped: {digit_fixed}")
    print(f"  Total cleaned: {invocation_fixed + digit_fixed}")
    print(f"  Unchanged: {total - invocation_fixed - digit_fixed}")


if __name__ == "__main__":
    main()
