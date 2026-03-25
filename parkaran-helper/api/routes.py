"""Flask API routes for the Parkaran Helper."""

from flask import Blueprint, jsonify, request
from enrichment.data_loader import load_enriched
from api.parkaran_builder import ParkaranBuilder
from api.parkaran_reviewer import ParkaranReviewer
from api.occasion_suggester import OccasionSuggester

api_bp = Blueprint("api", __name__)

# Load data once at import time
_shabads = None
_keertanis = None
_builder = None
_reviewer = None
_occasion_suggester = None
_banidb_matcher = None
_theme_enricher = None


def _get_data():
    global _shabads, _keertanis
    if _shabads is None:
        _shabads, _keertanis = load_enriched()
    return _shabads, _keertanis


def _get_builder():
    global _builder
    if _builder is None:
        shabads, _ = _get_data()
        _builder = ParkaranBuilder(shabads)
    return _builder


def _get_reviewer():
    global _reviewer
    if _reviewer is None:
        shabads, _ = _get_data()
        _reviewer = ParkaranReviewer(shabads)
    return _reviewer


def _get_occasion_suggester():
    global _occasion_suggester
    if _occasion_suggester is None:
        shabads, _ = _get_data()
        _occasion_suggester = OccasionSuggester(shabads)
    return _occasion_suggester


def _get_banidb_matcher():
    global _banidb_matcher
    if _banidb_matcher is None:
        from enrichment.banidb_matcher import BaniDBMatcher
        _banidb_matcher = BaniDBMatcher()
    return _banidb_matcher


def _get_theme_enricher():
    global _theme_enricher
    if _theme_enricher is None:
        from enrichment.claude_enricher import ThemeEnricher
        _theme_enricher = ThemeEnricher()
    return _theme_enricher


# --- Shabad endpoints ---

@api_bp.route("/shabads")
def list_shabads():
    shabads, _ = _get_data()
    q = request.args.get("q", "").lower()
    keertani = request.args.get("keertani")
    raag = request.args.get("raag")
    confidence = request.args.get("confidence")

    filtered = shabads
    if q:
        filtered = [
            s for s in filtered
            if q in s["title"].lower()
            or q in (s.get("primary_theme") or "").lower()
            or q in (s.get("keertani") or "").lower()
            or q in (s.get("english_translation") or "").lower()
        ]
    if keertani:
        filtered = [s for s in filtered if s.get("keertani") == keertani]
    if raag:
        filtered = [
            s for s in filtered
            if s.get("sggs_raag") == raag or s.get("performance_raag") == raag
        ]
    if confidence:
        filtered = [s for s in filtered if s.get("confidence") == confidence]

    # Return slim version for list view
    return jsonify([
        {
            "id": s["id"],
            "title": s["title"],
            "keertani": s.get("keertani"),
            "sggs_raag": s.get("sggs_raag"),
            "performance_raag": s.get("performance_raag"),
            "ang_number": s.get("ang_number"),
            "writer": s.get("writer"),
            "primary_theme": s.get("primary_theme"),
            "mood": s.get("mood"),
            "confidence": s.get("confidence"),
            "enrichment_status": s.get("enrichment_status"),
            "banidb_shabad_id": s.get("banidb_shabad_id"),
        }
        for s in filtered
    ])


@api_bp.route("/shabads/<int:shabad_id>")
def get_shabad(shabad_id):
    shabads, _ = _get_data()
    for s in shabads:
        if s["id"] == shabad_id:
            return jsonify(s)
    return jsonify({"error": "Shabad not found"}), 404


@api_bp.route("/shabads/<int:shabad_id>/verses")
def get_shabad_verses(shabad_id):
    """Get verse-level data for a personal library shabad via its BaniDB ID."""
    shabads, _ = _get_data()
    shabad = None
    for s in shabads:
        if s["id"] == shabad_id:
            shabad = s
            break
    if not shabad:
        return jsonify({"error": "Shabad not found"}), 404

    banidb_id = shabad.get("banidb_shabad_id")
    if not banidb_id:
        return jsonify({"verses": [], "rahao_index": -1, "note": "No BaniDB match for this shabad"})

    # Delegate to BaniDB verse fetch
    matcher = _get_banidb_matcher()
    shabad_data = matcher.get_shabad(banidb_id)
    if not shabad_data:
        return jsonify({"verses": [], "rahao_index": -1})

    verses = []
    rahao_index = -1
    for i, v in enumerate(shabad_data.get("verses", [])):
        translit = v.get("transliteration", {})
        eng_translit = translit.get("en", "") if isinstance(translit, dict) else ""

        translation = v.get("translation", {})
        en_trans = translation.get("en", {}) if isinstance(translation, dict) else {}
        if isinstance(en_trans, dict):
            eng = en_trans.get("bdb") or en_trans.get("ms") or en_trans.get("ssk") or ""
        else:
            eng = ""

        gurmukhi = v.get("verse", {})
        gur_text = gurmukhi.get("unicode", "") if isinstance(gurmukhi, dict) else ""

        is_rahao = "rahaau" in eng_translit.lower()
        if is_rahao and rahao_index == -1:
            rahao_index = i

        verses.append({
            "index": i,
            "transliteration": eng_translit,
            "english": eng,
            "gurmukhi": gur_text,
            "is_rahao": is_rahao,
        })

    return jsonify({
        "shabad_id": shabad_id,
        "banidb_shabad_id": banidb_id,
        "verses": verses,
        "rahao_index": rahao_index,
    })


@api_bp.route("/keertanis")
def list_keertanis():
    _, keertanis = _get_data()
    return jsonify(keertanis)


@api_bp.route("/raags")
def list_raags():
    shabads, _ = _get_data()
    sggs_raags = sorted(set(
        s["sggs_raag"] for s in shabads if s.get("sggs_raag")
    ))
    performance_raags = sorted(set(
        s["performance_raag"] for s in shabads if s.get("performance_raag")
    ))
    return jsonify({"sggs_raags": sggs_raags, "performance_raags": performance_raags})


# --- Discover (BaniDB search) ---

@api_bp.route("/discover/search")
def discover_search():
    """Search BaniDB for shabads matching a query."""
    q = request.args.get("q", "").strip()
    searchtype = request.args.get("searchtype", 4, type=int)

    # For first-letter search (types 1 & 2), strip spaces so "h k s j k" → "hksjk"
    if searchtype in (1, 2):
        q = q.replace(" ", "")

    if not q or len(q) < 2:
        return jsonify([])

    matcher = _get_banidb_matcher()
    verses = matcher.search(q, searchtype=searchtype)

    # Deduplicate by shabadId, keep first verse per shabad
    seen = {}
    for v in verses:
        sid = v.get("shabadId")
        if sid and sid not in seen:
            seen[sid] = v

    # Cross-reference with personal DB
    shabads_data, _ = _get_data()
    personal_lookup = {
        s.get("banidb_shabad_id"): s["id"]
        for s in shabads_data if s.get("banidb_shabad_id")
    }

    results = []
    for sid, verse in seen.items():
        translit = verse.get("transliteration", {})
        translation = verse.get("translation", {})
        en_trans = translation.get("en", {}) if isinstance(translation, dict) else {}

        results.append({
            "banidb_shabad_id": sid,
            "title_gurmukhi": (verse.get("verse", {}).get("unicode", "")
                              if isinstance(verse.get("verse"), dict) else ""),
            "title_transliteration": (translit.get("en", "")
                                     if isinstance(translit, dict) else ""),
            "first_line_translation": ((en_trans.get("bdb") or en_trans.get("ms") or "")
                                      if isinstance(en_trans, dict) else ""),
            "ang_number": verse.get("pageNo"),
            "raag": (verse.get("raag", {}).get("english", "")
                    if isinstance(verse.get("raag"), dict) else ""),
            "writer": (verse.get("writer", {}).get("english", "")
                      if isinstance(verse.get("writer"), dict) else ""),
            "in_personal_db": sid in personal_lookup,
            "personal_db_id": personal_lookup.get(sid),
        })

    return jsonify(results[:30])


@api_bp.route("/discover/shabad/<int:banidb_shabad_id>")
def discover_shabad(banidb_shabad_id):
    """Get full details for a BaniDB shabad."""
    matcher = _get_banidb_matcher()
    shabad_data = matcher.get_shabad(banidb_shabad_id)

    if not shabad_data:
        return jsonify({"error": "Shabad not found in BaniDB"}), 404

    enrichment = matcher.extract_enrichment(shabad_data)

    # Check personal DB
    shabads_data, _ = _get_data()
    personal_lookup = {
        s.get("banidb_shabad_id"): s["id"]
        for s in shabads_data if s.get("banidb_shabad_id")
    }

    # Check for cached themes
    cached_themes = matcher.get_cached_enrichment(banidb_shabad_id)

    result = {
        **enrichment,
        "verse_count": len(shabad_data.get("verses", [])),
        "in_personal_db": banidb_shabad_id in personal_lookup,
        "personal_db_id": personal_lookup.get(banidb_shabad_id),
    }

    if cached_themes:
        result.update(cached_themes)

    return jsonify(result)


@api_bp.route("/discover/shabad/<int:banidb_shabad_id>/verses")
def discover_shabad_verses(banidb_shabad_id):
    """Get verse-level data for a BaniDB shabad with rahao detection."""
    matcher = _get_banidb_matcher()
    shabad_data = matcher.get_shabad(banidb_shabad_id)

    if not shabad_data:
        return jsonify({"error": "Shabad not found in BaniDB"}), 404

    verses = []
    rahao_index = -1
    for i, v in enumerate(shabad_data.get("verses", [])):
        translit = v.get("transliteration", {})
        eng_translit = translit.get("en", "") if isinstance(translit, dict) else ""

        translation = v.get("translation", {})
        en_trans = translation.get("en", {}) if isinstance(translation, dict) else {}
        if isinstance(en_trans, dict):
            eng = en_trans.get("bdb") or en_trans.get("ms") or en_trans.get("ssk") or ""
        else:
            eng = ""

        gurmukhi = v.get("verse", {})
        gur_text = gurmukhi.get("unicode", "") if isinstance(gurmukhi, dict) else ""

        is_rahao = "rahaau" in eng_translit.lower()
        if is_rahao and rahao_index == -1:
            rahao_index = i

        verses.append({
            "index": i,
            "transliteration": eng_translit,
            "english": eng,
            "gurmukhi": gur_text,
            "is_rahao": is_rahao,
        })

    return jsonify({
        "banidb_shabad_id": banidb_shabad_id,
        "verses": verses,
        "rahao_index": rahao_index,
    })


@api_bp.route("/discover/enrich", methods=["POST"])
def discover_enrich():
    """On-the-fly Claude theme extraction for a discovered shabad."""
    data = request.get_json()
    banidb_shabad_id = data.get("banidb_shabad_id")

    if not banidb_shabad_id:
        return jsonify({"error": "banidb_shabad_id required"}), 400

    # Check cache first
    matcher = _get_banidb_matcher()
    cached = matcher.get_cached_enrichment(banidb_shabad_id)
    if cached:
        return jsonify(cached)

    # Build a shabad-like dict for the enricher
    shabad_for_enrichment = {
        "title": data.get("transliteration", "")[:100] or f"Shabad {banidb_shabad_id}",
        "transliteration": data.get("transliteration", ""),
        "english_translation": data.get("english_translation", ""),
        "sggs_raag": data.get("raag", ""),
        "writer": data.get("writer", ""),
    }

    enricher = _get_theme_enricher()
    results = enricher.extract_themes_batch([shabad_for_enrichment])

    if results and results[0]:
        themes = results[0]
        matcher.cache_enrichment(banidb_shabad_id, themes)
        return jsonify(themes)

    return jsonify({"error": "Could not extract themes"}), 500


# --- Parkaran Builder ---

@api_bp.route("/parkaran/build", methods=["POST"])
def build_parkaran():
    data = request.get_json()
    seed_ids = data.get("seed_shabads", [])
    banidb_seeds = data.get("seed_banidb_shabads", [])
    max_results = data.get("max_results", 10)
    filters = data.get("filters")
    source = data.get("source", "personal")
    mukhra_texts = data.get("mukhra_texts", [])

    if not seed_ids and not banidb_seeds:
        return jsonify({"error": "Provide at least 1 seed shabad"}), 400

    builder = _get_builder()
    result = builder.build(
        seed_ids, max_results, filters,
        banidb_seeds=banidb_seeds, source=source, mukhra_texts=mukhra_texts
    )
    return jsonify(result)


# --- Parkaran Reviewer ---

@api_bp.route("/parkaran/review", methods=["POST"])
def review_parkaran():
    data = request.get_json()
    shabad_ids = data.get("shabad_ids", [])

    if len(shabad_ids) < 2:
        return jsonify({"error": "Provide at least 2 shabad IDs to review"}), 400

    reviewer = _get_reviewer()
    result = reviewer.review(shabad_ids)
    return jsonify(result)


# --- Occasions ---

@api_bp.route("/occasions")
def list_occasions():
    suggester = _get_occasion_suggester()
    return jsonify(suggester.get_occasions())


@api_bp.route("/occasions/<occasion_id>/suggest")
def suggest_for_occasion(occasion_id):
    count = request.args.get("count", 10, type=int)
    keertani = request.args.get("keertani")

    suggester = _get_occasion_suggester()
    result = suggester.suggest(occasion_id, count, keertani)
    return jsonify(result)
