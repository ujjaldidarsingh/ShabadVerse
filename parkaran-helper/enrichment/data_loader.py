"""Load shabad data from Excel and save/load enriched JSON."""

import json
import os
import pandas as pd
import config


def load_from_excel():
    """Load shabads and keertanis from the Excel database."""
    xl = pd.ExcelFile(config.EXCEL_PATH)

    # Load keertanis
    keertanis_df = xl.parse("Keertani Master List")
    keertanis = []
    for _, row in keertanis_df.iterrows():
        keertanis.append({
            "id": int(row["#"]),
            "name": str(row["Keertani Name"]).strip(),
            "era": str(row.get("Era", "")).strip(),
            "lineage": str(row.get("Primary Lineage/School", "")).strip(),
            "archive_link": str(row.get("Archive Link", "")).strip(),
        })

    # Load shabads
    tracks_df = xl.parse("Keertan Track Database")
    shabads = []
    for idx, row in tracks_df.iterrows():
        title = str(row.get("Shabad/Title", "")).strip()
        if not title or title == "nan":
            continue
        shabads.append({
            "id": idx + 1,
            "title": title,
            "keertani": str(row.get("Keertani", "")).strip(),
            "performance_raag": _clean_field(row.get("Raag")),
            "taal_style": _clean_field(row.get("Taal/Style")),
            "confidence": str(row.get("Confidence", "Medium")).strip(),
            "link": _clean_field(row.get("Link")),
            "notes": _clean_field(row.get("Notes")),
            # Enrichment fields (filled later)
            "ang_number": None,
            "sggs_raag": None,
            "writer": None,
            "gurmukhi_text": None,
            "english_translation": None,
            "transliteration": None,
            "banidb_shabad_id": None,
            "primary_theme": None,
            "secondary_themes": [],
            "occasions": [],
            "mood": None,
            "brief_meaning": None,
            "match_confidence": None,
            "enrichment_status": "pending",
        })

    return shabads, keertanis


def _clean_field(value):
    """Return None for NaN/empty, else stripped string."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s if s and s != "nan" else None


def save_enriched(shabads, keertanis):
    """Save enriched data to JSON."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    data = {
        "shabads": shabads,
        "keertanis": keertanis,
        "metadata": {
            "total_shabads": len(shabads),
            "enriched_count": sum(
                1 for s in shabads if s["enrichment_status"] == "complete"
            ),
        },
    }
    with open(config.ENRICHED_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(shabads)} shabads to {config.ENRICHED_DATA_PATH}")


def load_enriched():
    """Load enriched data from JSON. Returns (shabads, keertanis)."""
    with open(config.ENRICHED_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["shabads"], data["keertanis"]
