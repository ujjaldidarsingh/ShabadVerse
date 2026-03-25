"""Fetch all SGGS shabads from BaniDB and save locally.

Iterates through all 1430 angs (pages) of SGGS, extracts unique shabads
with their first-line translation/transliteration directly from the ang data.
No individual shabad fetches needed — everything comes from the ang endpoint.
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import requests


def fetch_ang_with_retry(session, base_url, ang, max_retries=4):
    """Fetch a single ang with exponential backoff on rate limits."""
    for attempt in range(max_retries):
        try:
            resp = session.get(
                f"{base_url}/angs/{ang}/{config.BANIDB_SOURCE}",
                timeout=15,
            )
            if resp.status_code == 429:
                wait = 5 * (2**attempt)
                print(f"    Rate limited on ang {ang}, waiting {wait}s (attempt {attempt + 1})...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 5 * (2**attempt)
                time.sleep(wait)
            else:
                print(f"  Failed ang {ang} after {max_retries} attempts: {e}")
    return None


def extract_verse_data(verse):
    """Extract transliteration, translation, and metadata from a verse."""
    translit = verse.get("transliteration", {})
    eng_translit = translit.get("en", "") if isinstance(translit, dict) else ""

    translation = verse.get("translation", {})
    en_trans = translation.get("en", {}) if isinstance(translation, dict) else {}
    if isinstance(en_trans, dict):
        eng = en_trans.get("bdb") or en_trans.get("ms") or en_trans.get("ssk") or ""
    else:
        eng = ""

    v = verse.get("verse", {})
    gurmukhi = v.get("unicode", "") if isinstance(v, dict) else ""

    raag = verse.get("raag", {})
    writer = verse.get("writer", {})

    return {
        "transliteration": eng_translit,
        "english_translation": eng,
        "gurmukhi": gurmukhi,
        "sggs_raag": raag.get("english", "") if isinstance(raag, dict) else "",
        "writer": writer.get("english", "") if isinstance(writer, dict) else "",
    }


def fetch_all_sggs():
    """Fetch all unique shabads from SGGS via BaniDB ang-by-ang.

    Collects all verses per shabad from the ang endpoint directly,
    concatenating multi-verse shabads without needing individual shabad fetches.
    """
    session = requests.Session()
    base_url = config.BANIDB_BASE_URL
    # shabad_id -> {data + verses list}
    shabads = {}

    print("Fetching all SGGS shabads from BaniDB (1430 angs)...")
    print("Extracting all data directly from ang pages — no individual shabad fetches.\n")

    failed_angs = []

    for ang in range(1, 1431):
        if ang % 50 == 0 or ang == 1:
            print(f"  Ang {ang}/1430 ({len(shabads)} shabads so far)...")

        data = fetch_ang_with_retry(session, base_url, ang)
        if data is None:
            failed_angs.append(ang)
            continue

        page = data.get("page", [])
        for verse in page:
            shabad_id = verse.get("shabadId")
            if not shabad_id:
                continue

            vdata = extract_verse_data(verse)

            if shabad_id not in shabads:
                # First verse of this shabad — create entry
                shabads[shabad_id] = {
                    "banidb_shabad_id": shabad_id,
                    "ang_number": ang,
                    "sggs_raag": vdata["sggs_raag"],
                    "writer": vdata["writer"],
                    "verses_translit": [vdata["transliteration"]],
                    "verses_eng": [vdata["english_translation"]],
                    "verses_gurmukhi": [vdata["gurmukhi"]],
                }
            else:
                # Additional verse of same shabad — append
                shabads[shabad_id]["verses_translit"].append(vdata["transliteration"])
                shabads[shabad_id]["verses_eng"].append(vdata["english_translation"])
                shabads[shabad_id]["verses_gurmukhi"].append(vdata["gurmukhi"])

        time.sleep(0.5)

    # Retry failed angs
    if failed_angs:
        print(f"\n  Retrying {len(failed_angs)} failed angs...")
        time.sleep(10)
        for ang in failed_angs:
            data = fetch_ang_with_retry(session, base_url, ang, max_retries=5)
            if data:
                page = data.get("page", [])
                for verse in page:
                    shabad_id = verse.get("shabadId")
                    if not shabad_id:
                        continue
                    vdata = extract_verse_data(verse)
                    if shabad_id not in shabads:
                        shabads[shabad_id] = {
                            "banidb_shabad_id": shabad_id,
                            "ang_number": ang,
                            "sggs_raag": vdata["sggs_raag"],
                            "writer": vdata["writer"],
                            "verses_translit": [vdata["transliteration"]],
                            "verses_eng": [vdata["english_translation"]],
                            "verses_gurmukhi": [vdata["gurmukhi"]],
                        }
                    else:
                        shabads[shabad_id]["verses_translit"].append(vdata["transliteration"])
                        shabads[shabad_id]["verses_eng"].append(vdata["english_translation"])
                        shabads[shabad_id]["verses_gurmukhi"].append(vdata["gurmukhi"])
            time.sleep(2)

    # Flatten verses into single strings
    shabads_list = []
    for s in shabads.values():
        shabads_list.append({
            "banidb_shabad_id": s["banidb_shabad_id"],
            "ang_number": s["ang_number"],
            "sggs_raag": s["sggs_raag"],
            "writer": s["writer"],
            "transliteration": " ".join(v for v in s["verses_translit"] if v),
            "english_translation": " ".join(v for v in s["verses_eng"] if v),
            "gurmukhi_text": "\n".join(v for v in s["verses_gurmukhi"] if v),
        })

    # Save
    os.makedirs(config.DATA_DIR, exist_ok=True)
    output_path = config.SGGS_DATA_PATH

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(shabads_list, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Saved {len(shabads_list)} SGGS shabads to {output_path}")
    if failed_angs:
        still_failed = [a for a in failed_angs]
        print(f"  {len(still_failed)} angs had issues. Run again to fill gaps.")
    return shabads_list


if __name__ == "__main__":
    fetch_all_sggs()
