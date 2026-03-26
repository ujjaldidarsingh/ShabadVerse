"""Extract full rahao pada from BaniDB verse data.

Uses the cached BaniDB verse arrays (not flat transliteration strings) to properly
detect the rahao pada boundaries. A rahao pada consists of all verses between the
previous numbered pada marker (e.g. ||1||) and the rahao marker (|| rahaau ||).

Example: Shabad 130 (Siree Raag Mahalla 5)
  Verses [0]: Title (Sireeraag Mahalaa 5)
  Verses [1-3]: Pada 1 (ends with ||1||)
  Verses [4-5]: Rahao pada (ਮਨ ਮੇਰੇ ਸੁਖ ਸਹਜ... + ਆਠ ਪਹਰ ਪ੍ਰਭੁ ਧਿਆਇ... ||1|| ਰਹਾਉ ||)
  Verses [6-9]: Pada 2
  ... etc
"""

import sys
import os
import json
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from enrichment.banidb_matcher import BaniDBMatcher


def is_pada_end(translit):
    """Check if a verse ends with a numbered pada marker like ||1||, ||2||, etc."""
    return bool(re.search(r'\|\|\d+\|\|\s*$', translit))


def is_rahao(translit):
    """Check if a verse contains the rahao marker pattern (|| rahaau || or ||1|| rahaau ||)."""
    return bool(re.search(r'\|\|.*rahaau.*\|\|', translit.lower()))


def is_title_line(translit):
    """Check if a verse is a title/heading line (raag name, mahalla, etc.)."""
    clean = translit.strip().lower()
    title_patterns = [
        r'^(raag|siree|aasaa|soohee|bilaaval|gauree|dhanaasaree|todee|bairaaree|tilang)',
        r'^(sorath|maajh|vaddhans|jaitsaree|kedhaaraa|bhairo|basant|maaroo|malaar)',
        r'^(kaanarre|prabhaatee|salok|mahalaa|goojaree|raamkalee|nat|maalee gaurraa)',
        r'^(gond|tukhaari|suhi|devaga(n)?dharee|wadhaha(n)?s|saarang|nut)',
        r'^(aasaavaree|kaliyaan|bihaagraa|jap|so (dhar|purakh))',
    ]
    for pat in title_patterns:
        if re.match(pat, clean):
            return True
    # Also: very short lines that are just markers
    if len(clean) < 5:
        return True
    return False


def extract_rahao_pada(verses):
    """Extract the full rahao pada from a BaniDB verse array.

    Returns dict with rahao_gurmukhi, rahao_english, rahao_start_verse, rahao_end_verse.
    Returns empty dict if no rahao found.
    """
    if not verses:
        return {}

    # Step 1: Find the first verse with rahao marker
    rahao_idx = -1
    for i, v in enumerate(verses):
        translit = v.get("transliteration", {})
        eng_translit = translit.get("en", "") if isinstance(translit, dict) else ""
        if is_rahao(eng_translit):
            rahao_idx = i
            break

    if rahao_idx < 0:
        return {}

    # Step 2: Walk backwards to find the start of the rahao pada
    # The pada starts after the previous numbered pada marker (||1||, ||2||, etc.)
    # or after the title line
    pada_start = rahao_idx  # default: just the rahao line itself

    for j in range(rahao_idx - 1, -1, -1):
        j_translit = verses[j].get("transliteration", {})
        j_eng_translit = j_translit.get("en", "") if isinstance(j_translit, dict) else ""

        # Stop if we hit a numbered pada end (||1||, ||2||)
        if is_pada_end(j_eng_translit):
            pada_start = j + 1
            break

        # Stop if we hit a title line
        if is_title_line(j_eng_translit):
            pada_start = j + 1
            break

        # Include this verse in the pada
        pada_start = j

    # Step 3: Extract Gurmukhi and English for the full pada
    gurmukhi_lines = []
    english_lines = []

    for k in range(pada_start, rahao_idx + 1):
        v = verses[k]

        # Gurmukhi
        gur = v.get("verse", {})
        gur_text = gur.get("unicode", "") if isinstance(gur, dict) else ""
        if gur_text:
            gurmukhi_lines.append(gur_text)

        # English translation
        translation = v.get("translation", {})
        en_trans = translation.get("en", {}) if isinstance(translation, dict) else {}
        if isinstance(en_trans, dict):
            eng = en_trans.get("bdb") or en_trans.get("ms") or en_trans.get("ssk") or ""
        else:
            eng = ""
        if eng:
            english_lines.append(eng)

    if not gurmukhi_lines:
        return {}

    return {
        "rahao_gurmukhi": "\n".join(gurmukhi_lines),
        "rahao_english": " ".join(english_lines),
        "rahao_start_verse": pada_start,
        "rahao_end_verse": rahao_idx,
    }


def add_rahao_pada():
    """Extract full rahao pada for all SGGS shabads using BaniDB verse data."""
    sggs_path = config.SGGS_DATA_PATH
    if not os.path.exists(sggs_path):
        print(f"SGGS data not found at {sggs_path}")
        return

    print("Loading SGGS shabads...")
    with open(sggs_path, encoding="utf-8") as f:
        shabads = json.load(f)

    print(f"Processing {len(shabads)} shabads for rahao pada detection...")

    matcher = BaniDBMatcher()
    found = 0
    multi_line = 0
    cached = 0
    fetched = 0

    for i, s in enumerate(shabads):
        if i % 500 == 0:
            print(f"  Processing {i}/{len(shabads)} ({found} rahao found, {multi_line} multi-line)...")

        sid = s["banidb_shabad_id"]

        # Get verse data from BaniDB (cached in SQLite)
        shabad_data = matcher.get_shabad(sid)
        if not shabad_data:
            s["rahao_gurmukhi"] = ""
            s["rahao_english"] = ""
            s["rahao_start_verse"] = -1
            s["rahao_end_verse"] = -1
            continue

        verses = shabad_data.get("verses", [])
        result = extract_rahao_pada(verses)

        if result:
            s["rahao_gurmukhi"] = result["rahao_gurmukhi"]
            s["rahao_english"] = result["rahao_english"]
            s["rahao_start_verse"] = result["rahao_start_verse"]
            s["rahao_end_verse"] = result["rahao_end_verse"]
            found += 1
            if result["rahao_start_verse"] != result["rahao_end_verse"]:
                multi_line += 1
        else:
            s["rahao_gurmukhi"] = ""
            s["rahao_english"] = ""
            s["rahao_start_verse"] = -1
            s["rahao_end_verse"] = -1

    matcher.close()

    print(f"\nResults:")
    print(f"  Total shabads: {len(shabads)}")
    print(f"  With rahao: {found} ({found * 100 // len(shabads)}%)")
    print(f"  Multi-line pada: {multi_line} ({multi_line * 100 // max(1, found)}% of rahao shabads)")
    print(f"  Single-line: {found - multi_line}")

    # Save
    with open(sggs_path, "w", encoding="utf-8") as f:
        json.dump(shabads, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {sggs_path}")

    # Quick verification on known shabad
    s130 = next((s for s in shabads if s["banidb_shabad_id"] == 130), None)
    if s130:
        print(f"\nVerification — Shabad 130 (man mere sukh sahaj):")
        print(f"  rahao_gurmukhi: {s130.get('rahao_gurmukhi', 'MISSING')[:100]}")
        print(f"  rahao_english: {s130.get('rahao_english', 'MISSING')[:100]}")
        print(f"  verses: {s130.get('rahao_start_verse')} → {s130.get('rahao_end_verse')}")


def is_title_line_gurmukhi(gurmukhi_line):
    """Check if a Gurmukhi verse line is a raag/section title or structural header."""
    clean = gurmukhi_line.strip()
    if len(clean) < 5:
        return True
    # Gurmukhi raag name patterns (all 31 SGGS raags + structural markers)
    raag_patterns = [
        r'^(ਸਿਰੀਰਾਗ|ਆਸਾ|ਗਉੜੀ|ਸੂਹੀ|ਬਿਲਾਵਲ|ਧਨਾਸਰੀ|ਟੋਡੀ|ਬੈਰਾੜੀ|ਤਿਲੰਗ)',
        r'^(ਸੋਰਠਿ|ਮਾਝ|ਵਡਹੰਸ|ਜੈਤਸਰੀ|ਕੇਦਾਰਾ|ਭੈਰਉ|ਬਸੰਤ|ਮਾਰੂ|ਮਲਾਰ)',
        r'^(ਕਾਨੜਾ|ਪ੍ਰਭਾਤੀ|ਸਲੋਕ|ਮਹਲਾ|ਗੂਜਰੀ|ਰਾਮਕਲੀ|ਨਟ|ਮਾਲੀ ਗਉੜਾ)',
        r'^(ਗੋਂਡ|ਟੁਖਾਰੀ|ਦੇਵਗੰਧਾਰੀ|ਸਾਰੰਗ|ਨੁਟ|ਆਸਾਵਰੀ|ਕਲਿਆਣ|ਬਿਹਾਗੜਾ)',
        r'^(ਰਾਗੁ|ਵਾਰ|ਛੰਤ|ਪਉੜੀ|ਅਸਟਪਦੀ|ਚਉਪਦੇ|ਘਰੁ|ਇਕੋਅੰਕਾਰ)',
        r'^(॥ ਜਪੁ ॥|ਸੋ ਦਰੁ ਰਾਗੁ|ਸੋ ਪੁਰਖੁ ਰਾਗੁ)',
        r'^(ਡਖਣਾ|ਪਵੜੀ|ਦੋਹਰਾ|ਸਵੱਯੇ|ਕਬਿੱਤ)',
    ]
    for pat in raag_patterns:
        if re.match(pat, clean):
            return True
    # Lines that are just "ਮਹਲਾ X" or "ਮਃ X"
    if re.match(r'^(ਮਹਲਾ|ਮਃ)\s*[੧੨੩੪੫੬੭੮੯]', clean):
        return True
    # Very short lines ending with ॥ are structural markers
    if len(clean) < 15 and '॥' in clean:
        return True
    return False


def fix_display_names():
    """Fix shabads whose display_gurmukhi uses a raag/section header instead of content.

    Priority: rahao_gurmukhi > first non-title verse line from gurmukhi_text.
    """
    sggs_path = config.SGGS_DATA_PATH
    if not os.path.exists(sggs_path):
        print(f"SGGS data not found at {sggs_path}")
        return

    print("\nFixing display names (raag headers → content lines)...")
    with open(sggs_path, encoding="utf-8") as f:
        shabads = json.load(f)

    fixed = 0
    for s in shabads:
        dg = s.get("display_gurmukhi", "")
        if not dg or not is_title_line_gurmukhi(dg):
            continue

        # Priority 1: use rahao_gurmukhi
        if s.get("rahao_gurmukhi"):
            # Take first line of rahao pada (it can be multi-line)
            first_rahao = s["rahao_gurmukhi"].split("\n")[0].strip()
            if first_rahao and not is_title_line_gurmukhi(first_rahao):
                s["display_gurmukhi"] = first_rahao
                fixed += 1
                continue

        # Priority 2: find first non-title verse line from gurmukhi_text
        gurmukhi_text = s.get("gurmukhi_text", "")
        if gurmukhi_text:
            for line in gurmukhi_text.split("\n"):
                line = line.strip()
                if line and not is_title_line_gurmukhi(line) and len(line) > 8:
                    s["display_gurmukhi"] = line
                    fixed += 1
                    break

    # Save
    with open(sggs_path, "w", encoding="utf-8") as f:
        json.dump(shabads, f, ensure_ascii=False, indent=2)

    print(f"  Fixed {fixed} display names")
    return fixed


if __name__ == "__main__":
    add_rahao_pada()
    fix_display_names()
