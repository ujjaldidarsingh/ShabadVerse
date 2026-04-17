"""Search BaniDB API and fuzzy-match shabads against user titles."""

import re
import sqlite3
import json
import time
from difflib import SequenceMatcher
from urllib.parse import quote

import requests
import config


class BaniDBMatcher:
    def __init__(self):
        self.base_url = config.BANIDB_BASE_URL
        self.session = requests.Session()
        self._init_cache()

    def _init_cache(self):
        """Initialize SQLite cache for API responses."""
        self.conn = sqlite3.connect(config.CACHE_DB_PATH, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                query TEXT PRIMARY KEY,
                response TEXT,
                timestamp REAL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS shabad_cache (
                shabad_id INTEGER PRIMARY KEY,
                response TEXT,
                timestamp REAL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS enrichment_cache (
                banidb_shabad_id INTEGER PRIMARY KEY,
                themes_json TEXT,
                timestamp REAL
            )
        """)
        self.conn.commit()

    def match_shabad(self, title):
        """
        Try to match a user's shabad title to a BaniDB shabad.
        Returns dict with enrichment data, or None if no match.
        """
        cleaned = self._clean_title(title)
        if not cleaned:
            return None

        # Try progressively shorter queries (always use English keyword for title matching)
        words = cleaned.split()
        for end in range(len(words), max(1, len(words) - 3), -1):
            query = " ".join(words[:end])
            results = self.search(query, searchtype=4)
            if results and len(results) <= 500:
                break
        else:
            # Last resort: just first 2 words
            query = " ".join(words[:2])
            results = self.search(query, searchtype=4)

        if not results:
            return None

        # Score each search result verse directly against user title
        best_match = None
        best_score = 0.0
        seen_shabads = set()

        for verse in results[:30]:
            sid = verse.get("shabadId")
            if not sid or sid in seen_shabads:
                continue
            seen_shabads.add(sid)

            score = self._score_verse(title, verse)

            if score > best_score:
                shabad_data = self.get_shabad(sid)
                if shabad_data:
                    best_score = score
                    best_match = shabad_data

        if best_match and best_score >= 0.4:
            return self.extract_enrichment(best_match, best_score)

        return None

    def _clean_title(self, title):
        """Clean a shabad title for search."""
        title = re.sub(r"\(.*?\)", "", title)
        title = re.sub(r"[^a-zA-Z\s]", "", title)
        title = title.strip().lower()
        return title

    def search(self, query, searchtype=None):
        """Search BaniDB with caching. Supports optional searchtype override."""
        stype = searchtype or config.BANIDB_SEARCH_TYPE
        cache_key = f"{query}||{stype}"

        # Check cache
        row = self.conn.execute(
            "SELECT response FROM search_cache WHERE query = ?", (cache_key,)
        ).fetchone()
        if row:
            return json.loads(row[0])

        url = f"{self.base_url}/search/{quote(query)}"
        params = {"searchtype": stype, "source": config.BANIDB_SOURCE}

        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            verses = data.get("verses", [])

            self.conn.execute(
                "INSERT OR REPLACE INTO search_cache (query, response, timestamp) VALUES (?, ?, ?)",
                (cache_key, json.dumps(verses), time.time()),
            )
            self.conn.commit()
            return verses
        except Exception as e:
            print(f"  BaniDB search error for '{query}': {e}")
            return []

    def get_shabad(self, shabad_id):
        """Get full shabad from BaniDB with caching and retry."""
        row = self.conn.execute(
            "SELECT response FROM shabad_cache WHERE shabad_id = ?", (shabad_id,)
        ).fetchone()
        if row:
            return json.loads(row[0])

        url = f"{self.base_url}/shabads/{shabad_id}"
        for attempt in range(4):
            time.sleep(0.5 * (2**attempt))  # 0.5, 1, 2, 4 seconds

            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code == 429:
                    continue  # retry with longer backoff
                resp.raise_for_status()
                data = resp.json()

                self.conn.execute(
                    "INSERT OR REPLACE INTO shabad_cache (shabad_id, response, timestamp) VALUES (?, ?, ?)",
                    (shabad_id, json.dumps(data), time.time()),
                )
                self.conn.commit()
                return data
            except Exception as e:
                if attempt == 3:
                    print(f"  BaniDB shabad error for ID {shabad_id}: {e}")
                    return None

    def extract_enrichment(self, shabad_data, confidence=1.0):
        """Extract enrichment fields from a BaniDB shabad response."""
        info = shabad_data.get("shabadInfo", {})
        verses = shabad_data.get("verses", [])

        raag = info.get("raag", {})
        raag_name = raag.get("english", "") if isinstance(raag, dict) else ""

        writer = info.get("writer", {})
        writer_name = writer.get("english", "") if isinstance(writer, dict) else ""

        page_no = info.get("pageNo") or (verses[0].get("pageNo") if verses else None)

        gurmukhi_parts = []
        english_parts = []
        translit_parts = []

        for verse in verses:
            v = verse.get("verse", {})
            gurmukhi = v.get("unicode", "") if isinstance(v, dict) else ""
            if gurmukhi:
                gurmukhi_parts.append(gurmukhi)

            translation = verse.get("translation", {})
            en_trans = translation.get("en", {}) if isinstance(translation, dict) else {}
            if isinstance(en_trans, dict):
                eng = en_trans.get("bdb") or en_trans.get("ms") or en_trans.get("ssk") or ""
            else:
                eng = ""
            if eng:
                english_parts.append(eng)

            translit = verse.get("transliteration", {})
            eng_translit = translit.get("en", "") if isinstance(translit, dict) else ""
            if eng_translit:
                translit_parts.append(eng_translit)

        return {
            "ang_number": page_no,
            "sggs_raag": raag_name or None,
            "writer": writer_name or None,
            "gurmukhi_text": "\n".join(gurmukhi_parts) or None,
            "english_translation": " ".join(english_parts) or None,
            "transliteration": " ".join(translit_parts) or None,
            "banidb_shabad_id": info.get("shabadId"),
            "match_confidence": round(confidence, 2),
        }

    def get_cached_enrichment(self, banidb_shabad_id):
        """Get cached Claude enrichment themes for a BaniDB shabad."""
        row = self.conn.execute(
            "SELECT themes_json FROM enrichment_cache WHERE banidb_shabad_id = ?",
            (banidb_shabad_id,),
        ).fetchone()
        if row:
            return json.loads(row[0])
        return None

    def cache_enrichment(self, banidb_shabad_id, themes):
        """Cache Claude enrichment themes for a BaniDB shabad."""
        self.conn.execute(
            "INSERT OR REPLACE INTO enrichment_cache (banidb_shabad_id, themes_json, timestamp) VALUES (?, ?, ?)",
            (banidb_shabad_id, json.dumps(themes), time.time()),
        )
        self.conn.commit()

    def _score_verse(self, user_title, verse):
        """Score a single verse against the user's title."""
        user_clean = self._clean_title(user_title).lower()
        user_norm = self._normalize_translit(user_clean)
        user_words = user_clean.split()

        translit = verse.get("transliteration", {})
        eng_translit = translit.get("en", "") if isinstance(translit, dict) else ""
        if not eng_translit:
            return 0.0

        eng_clean = re.sub(r"[^a-zA-Z\s]", "", eng_translit).lower().strip()
        eng_norm = self._normalize_translit(eng_clean)

        best = 0.0

        score = SequenceMatcher(None, user_clean, eng_clean).ratio()
        best = max(best, score)

        norm_score = SequenceMatcher(None, user_norm, eng_norm).ratio()
        best = max(best, norm_score)

        if eng_norm.startswith(user_norm[:min(12, len(user_norm))]):
            best = max(best, 0.85)

        eng_words = eng_clean.split()
        if user_words and eng_words:
            matched = 0
            for uw in user_words:
                uw_norm = self._normalize_translit(uw)
                for ew in eng_words:
                    ew_norm = self._normalize_translit(ew)
                    if uw_norm == ew_norm or SequenceMatcher(None, uw_norm, ew_norm).ratio() > 0.7:
                        matched += 1
                        break
            word_ratio = matched / len(user_words)
            best = max(best, word_ratio * 0.9)

        return best

    def _normalize_translit(self, text):
        """Normalize transliteration for comparison."""
        t = re.sub(r"[^a-zA-Z\s]", "", text).lower().strip()
        t = re.sub(r"aa+", "a", t)
        t = re.sub(r"ee+", "i", t)
        t = re.sub(r"oo+", "u", t)
        t = re.sub(r"ai", "e", t)
        t = re.sub(r"au", "o", t)
        t = re.sub(r"(.)\1+", r"\1", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def close(self):
        self.conn.close()
