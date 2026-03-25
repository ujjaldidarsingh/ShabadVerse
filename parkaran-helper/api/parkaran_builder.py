"""Core parkaran builder: seed shabads → themed suggestions.

Strategy: graph-first (instant, tag-based), vector-fallback, LLM explanations optional.
"""

import json
import os
import config
from database.vector_store import ShabadVectorStore
from llm.ollama_client import OllamaClient

GRAPH_PATH = os.path.join(config.DATA_DIR, "similarity_graph.json")


class ParkaranBuilder:
    def __init__(self, shabads_data):
        self.shabads = {s["id"]: s for s in shabads_data}
        self.vector_store = ShabadVectorStore()
        self.sggs_vector_store = None
        self.llm = OllamaClient()
        self._graph = None
        self._sggs_lookup = None

    def _get_graph(self):
        """Lazy-load the precomputed similarity graph."""
        if self._graph is None and os.path.exists(GRAPH_PATH):
            with open(GRAPH_PATH, encoding="utf-8") as f:
                self._graph = json.load(f)
        return self._graph

    def _get_sggs_lookup(self):
        """Lazy-load SGGS shabad data for graph results."""
        if self._sggs_lookup is None:
            sggs_path = config.SGGS_DATA_PATH
            if os.path.exists(sggs_path):
                with open(sggs_path, encoding="utf-8") as f:
                    sggs_list = json.load(f)
                self._sggs_lookup = {str(s["banidb_shabad_id"]): s for s in sggs_list}
            else:
                self._sggs_lookup = {}
        return self._sggs_lookup

    def _get_sggs_store(self):
        if self.sggs_vector_store is None:
            self.sggs_vector_store = ShabadVectorStore(
                collection_name=config.SGGS_COLLECTION_NAME
            )
        return self.sggs_vector_store

    def build(self, seed_ids, max_results=10, filters=None, banidb_seeds=None, source="personal", mukhra_texts=None):
        """
        Given seed shabad IDs and/or BaniDB seeds, suggest connecting shabads.
        source: "personal" (library only), "sggs" (all SGGS), or "all" (both).
        Strategy: graph-first (instant), vector-fallback, LLM explanations optional.
        """
        seeds = [self.shabads[sid] for sid in seed_ids if sid in self.shabads]
        banidb_seed_list = banidb_seeds or []
        all_seeds = seeds + banidb_seed_list

        if not all_seeds:
            return {"error": "No valid seed shabads found"}

        # Try graph-first (instant, tag-based) for any source
        graph = self._get_graph()
        if graph:
            graph_results = self._graph_suggestions(all_seeds, seed_ids, banidb_seed_list, max_results, source, filters)
            if graph_results and graph_results.get("suggestions"):
                return graph_results

        # Fallback to vector search
        return self._vector_suggestions(all_seeds, seed_ids, banidb_seed_list, max_results, source, filters, mukhra_texts)

    def _graph_suggestions(self, all_seeds, seed_ids, banidb_seed_list, max_results, source, filters):
        """Get suggestions from precomputed similarity graph (instant, no LLM)."""
        graph = self._get_graph()
        neighbors_map = graph.get("neighbors", {})
        metadata = graph.get("metadata", {})
        sggs_lookup = self._get_sggs_lookup()

        # Build graph keys for seeds
        seed_graph_keys = set()
        for s in all_seeds:
            if s.get("banidb_shabad_id"):
                seed_graph_keys.add(str(s["banidb_shabad_id"]))
            if s.get("id") and s["id"] in self.shabads:
                seed_graph_keys.add(f"personal_{s['id']}")
                # Also add the banidb ID if the personal shabad has one
                banidb_id = self.shabads[s["id"]].get("banidb_shabad_id")
                if banidb_id:
                    seed_graph_keys.add(str(banidb_id))

        if not seed_graph_keys:
            return None

        # Collect neighbors from all seeds, merge scores
        candidate_scores = {}  # id -> {score, shared_tags}
        for key in seed_graph_keys:
            for neighbor in neighbors_map.get(key, []):
                nid = neighbor["id"]
                if nid in seed_graph_keys:
                    continue  # skip self/other seeds
                if nid in candidate_scores:
                    # Merge: take max score, union shared tags
                    existing = candidate_scores[nid]
                    existing["score"] = max(existing["score"], neighbor["score"])
                    existing["shared_tags"] = list(set(existing["shared_tags"]) | set(neighbor["shared_tags"]))
                else:
                    candidate_scores[nid] = {
                        "score": neighbor["score"],
                        "shared_tags": list(neighbor["shared_tags"]),
                    }

        if not candidate_scores:
            return None

        # For "personal" source, map SGGS graph IDs back to personal library
        # (personal library is a subset of SGGS - same shabads, different IDs)
        personal_banidb_to_id = {}
        if source == "personal":
            for pid, pdata in self.shabads.items():
                if pdata.get("banidb_shabad_id"):
                    personal_banidb_to_id[str(pdata["banidb_shabad_id"])] = pid

        # Filter by source
        filtered = {}
        for nid, data in candidate_scores.items():
            if source == "personal":
                # Accept personal graph nodes OR SGGS IDs that map to personal library
                if nid.startswith("personal_"):
                    filtered[nid] = data
                elif nid in personal_banidb_to_id:
                    # Remap to personal ID
                    filtered[f"personal_{personal_banidb_to_id[nid]}"] = data
                continue
            if source == "sggs" and nid.startswith("personal_"):
                continue
            # Apply raag filter if present
            if filters and filters.get("sggs_raag"):
                meta = metadata.get(nid, {})
                if meta.get("raag") != filters["sggs_raag"]:
                    continue
            filtered[nid] = data

        # Sort by score, take top
        sorted_candidates = sorted(filtered.items(), key=lambda x: x[1]["score"], reverse=True)[:max_results]

        # Build suggestion objects
        suggestions = []
        for nid, data in sorted_candidates:
            meta = metadata.get(nid, {})
            shared_tags = data["shared_tags"]
            # Precomputed score already blends 50% tag Jaccard + 50% embedding cosine
            # Small diversity bonus: different shared tags = broader thematic connection
            base = data["score"]  # 0.0 to ~0.9 range
            diversity = min(len(set(shared_tags)) * 0.3, 1.0)
            score = round(max(1, min(10, base * 9 + diversity)), 1)

            if nid.startswith("personal_"):
                pid = int(nid.replace("personal_", ""))
                full = self.shabads.get(pid)
                if not full:
                    continue
                suggestions.append({
                    "id": pid,
                    "title": full.get("title", "Unknown"),
                    "sggs_raag": full.get("sggs_raag"),
                    "ang_number": full.get("ang_number"),
                    "writer": full.get("writer"),
                    "primary_theme": full.get("primary_theme"),
                    "mood": full.get("mood"),
                    "brief_meaning": full.get("brief_meaning"),
                    "connection_score": score,
                    "connection_explanation": f"Connected through: {', '.join(shared_tags[:4])}",
                    "suggested_position": "building",
                    "source": "personal",
                    "keertani": full.get("keertani"),
                    "performance_raag": full.get("performance_raag"),
                    "link": full.get("link"),
                    "shared_tags": shared_tags,
                })
            else:
                # SGGS shabad
                sggs_data = sggs_lookup.get(nid, {})
                title = meta.get("title") or (sggs_data.get("transliteration") or "")[:80] or "Unknown"
                suggestions.append({
                    "id": nid,
                    "title": title,
                    "banidb_shabad_id": int(nid) if nid.isdigit() else nid,
                    "sggs_raag": meta.get("raag") or sggs_data.get("sggs_raag"),
                    "ang_number": meta.get("ang") or sggs_data.get("ang_number"),
                    "writer": meta.get("writer") or sggs_data.get("writer"),
                    "primary_theme": meta.get("primary_theme") or sggs_data.get("primary_theme"),
                    "mood": meta.get("mood") or sggs_data.get("mood"),
                    "brief_meaning": sggs_data.get("brief_meaning"),
                    "connection_score": score,
                    "connection_explanation": f"Connected through: {', '.join(shared_tags[:4])}",
                    "suggested_position": "building",
                    "source": "sggs",
                    "english_translation": sggs_data.get("english_translation", "")[:300] if sggs_data else None,
                    "transliteration": sggs_data.get("transliteration"),
                    "rahao_english": sggs_data.get("rahao_english"),
                    "shared_tags": shared_tags,
                })

        if not suggestions:
            return None

        # Build parkaran theme from shared tags across all suggestions
        all_shared = set()
        for s in suggestions:
            all_shared.update(s.get("shared_tags", []))
        top_tags = sorted(all_shared, key=lambda t: sum(1 for s in suggestions if t in s.get("shared_tags", [])), reverse=True)
        parkaran_theme = f"Themes: {', '.join(top_tags[:5])}" if top_tags else ""

        return {
            "suggestions": suggestions,
            "parkaran_theme": parkaran_theme,
            "suggested_flow": [s["id"] for s in suggestions],
            "method": "graph",
        }

    def _vector_suggestions(self, all_seeds, seed_ids, banidb_seed_list, max_results, source, filters, mukhra_texts):
        """Fallback: vector search + optional LLM explanations."""
        # Build semantic query
        query_parts = []
        if mukhra_texts:
            for mt in mukhra_texts:
                if mt:
                    query_parts.append(mt)
        for s in all_seeds:
            if s.get("primary_theme"):
                query_parts.append(s["primary_theme"])
            if s.get("secondary_themes"):
                query_parts.extend(s["secondary_themes"])
            if s.get("mood"):
                query_parts.append(s["mood"])
            if s.get("brief_meaning"):
                query_parts.append(s["brief_meaning"])
        if not query_parts:
            for s in all_seeds:
                if s.get("english_translation"):
                    query_parts.append(s["english_translation"][:300])

        query_text = " | ".join(query_parts)

        # Build ChromaDB filter
        where_filter = None
        if filters:
            conditions = []
            if filters.get("keertani"):
                conditions.append({"keertani": filters["keertani"]})
            if filters.get("sggs_raag"):
                conditions.append({"sggs_raag": filters["sggs_raag"]})
            if filters.get("confidence"):
                conditions.append({"confidence": filters["confidence"]})
            if len(conditions) == 1:
                where_filter = conditions[0]
            elif len(conditions) > 1:
                where_filter = {"$and": conditions}

        enriched_candidates = []
        exclude = {str(sid) for sid in seed_ids}

        if source in ("personal", "all"):
            candidates = self.vector_store.search_similar(
                query_text, n_results=20, exclude_ids=exclude, where_filter=where_filter
            )
            for c in candidates:
                full = self.shabads.get(c["id"])
                if full:
                    enriched_candidates.append({**c, "shabad": full, "source": "personal"})

        if source in ("sggs", "all"):
            sggs_store = self._get_sggs_store()
            if sggs_store.get_count() > 0:
                sggs_exclude = {str(s.get("banidb_shabad_id")) for s in banidb_seed_list}
                if source == "all":
                    for s in self.shabads.values():
                        if s.get("banidb_shabad_id"):
                            sggs_exclude.add(str(s["banidb_shabad_id"]))

                sggs_filter = None
                if filters and filters.get("sggs_raag"):
                    sggs_filter = {"sggs_raag": filters["sggs_raag"]}

                sggs_candidates = sggs_store.search_similar(
                    query_text, n_results=20, exclude_ids=sggs_exclude, where_filter=sggs_filter
                )
                for c in sggs_candidates:
                    enriched_candidates.append({
                        **c,
                        "shabad": {
                            "title": c["metadata"].get("title", "Unknown"),
                            "banidb_shabad_id": c["id"],
                            "sggs_raag": c["metadata"].get("sggs_raag"),
                            "writer": c["metadata"].get("writer"),
                            "ang_number": c["metadata"].get("ang"),
                            "primary_theme": c["metadata"].get("primary_theme"),
                            "mood": c["metadata"].get("mood"),
                            "brief_meaning": c["metadata"].get("brief_meaning"),
                            "rahao_english": c["metadata"].get("rahao_english"),
                            "english_translation": c["document"][:300] if c.get("document") else None,
                        },
                        "source": "sggs",
                    })

        if banidb_seed_list and source == "personal":
            banidb_candidates = self._search_banidb_suggestions(all_seeds, seed_ids, banidb_seed_list)
            enriched_candidates.extend(banidb_candidates)

        if not enriched_candidates:
            return {"suggestions": [], "explanation": "No matching shabads found with the given filters."}

        return self._build_results(all_seeds, enriched_candidates, max_results)

    def _build_results(self, seeds, candidates, max_results):
        """Score candidates by vector distance, add LLM explanations if available."""
        candidates.sort(key=lambda c: c.get("distance") or 1.0)
        top_candidates = candidates[:max_results]

        suggestions = []
        for c in top_candidates:
            distance = c.get("distance") or 0.5
            score = round(max(1, min(10, (1 - distance) * 10)), 1)

            source = c.get("source", "personal")
            suggestion = {
                "id": c["id"],
                "title": c["shabad"].get("title", "Unknown"),
                "sggs_raag": c["shabad"].get("sggs_raag"),
                "ang_number": c["shabad"].get("ang_number"),
                "writer": c["shabad"].get("writer"),
                "primary_theme": c["shabad"].get("primary_theme"),
                "mood": c["shabad"].get("mood"),
                "brief_meaning": c["shabad"].get("brief_meaning"),
                "connection_score": score,
                "connection_explanation": "",
                "suggested_position": "building",
                "source": source,
            }

            if source == "personal":
                suggestion["keertani"] = c["shabad"].get("keertani")
                suggestion["performance_raag"] = c["shabad"].get("performance_raag")
                suggestion["link"] = c["shabad"].get("link")
            else:
                suggestion["banidb_shabad_id"] = c["shabad"].get("banidb_shabad_id")
                suggestion["english_translation"] = c["shabad"].get("english_translation")
                suggestion["transliteration"] = c["shabad"].get("transliteration")
                suggestion["rahao_english"] = c["shabad"].get("rahao_english")

            suggestions.append(suggestion)

        # LLM explanations (optional, non-blocking)
        parkaran_theme = ""
        if self.llm.is_available() and suggestions:
            try:
                llm_data = self._get_llm_explanations(seeds, suggestions)
                parkaran_theme = llm_data.get("parkaran_theme", "")
                llm_candidates = {str(c.get("id", "")): c for c in llm_data.get("candidates", [])}
                for s in suggestions:
                    lcd = llm_candidates.get(str(s["id"]), {})
                    if lcd.get("connection_explanation"):
                        s["connection_explanation"] = lcd["connection_explanation"]
                    if lcd.get("suggested_position"):
                        s["suggested_position"] = lcd["suggested_position"]
            except Exception:
                pass

        return {
            "suggestions": suggestions,
            "parkaran_theme": parkaran_theme,
            "suggested_flow": [s["id"] for s in suggestions],
            "method": "vector",
        }

    def _get_llm_explanations(self, seeds, suggestions):
        """Ask LLM for thematic explanations only (not scoring)."""
        seed_text = "\n".join(
            f"- \"{s.get('title', 'Unknown')}\": {s.get('primary_theme', 'N/A')} ({s.get('mood', 'N/A')})"
            for s in seeds
        )
        candidate_text = "\n".join(
            f"- ID {s['id']}: \"{s['title']}\" - Theme: {s.get('primary_theme', 'N/A')}, Mood: {s.get('mood', 'N/A')}"
            for s in suggestions
        )

        prompt = f"""You are a Sikh keertan parkaran expert. The musician chose these seed shabads:

{seed_text}

These candidates were found by thematic similarity:

{candidate_text}

For each candidate, provide:
1. "id": exactly as shown
2. "connection_explanation": 1 sentence explaining the thematic thread using Gurbani concepts
3. "suggested_position": "opening", "building", "climax", or "resolution"

Also provide "parkaran_theme": one sentence describing the overall bhaavanaa.

Return JSON with keys: "candidates" (array), "parkaran_theme" (string)."""

        return self.llm.generate_json(prompt, max_tokens=2000)

    def _search_banidb_suggestions(self, all_seeds, personal_seed_ids, banidb_seed_list):
        """Search BaniDB for thematic suggestions based on seed themes."""
        from enrichment.banidb_matcher import BaniDBMatcher

        keywords = set()
        for s in all_seeds:
            if s.get("primary_theme"):
                for word in s["primary_theme"].lower().split():
                    if len(word) > 3 and word not in {"with", "from", "that", "this", "than", "into", "upon"}:
                        keywords.add(word)
            if s.get("mood"):
                for word in s["mood"].lower().split():
                    if len(word) > 3 and word not in {"with", "from", "that", "this"}:
                        keywords.add(word)

        if not keywords:
            return []

        search_terms = list(keywords)[:3]
        query = " ".join(search_terms)

        matcher = BaniDBMatcher()
        verses = matcher.search(query, searchtype=4)

        banidb_seed_ids = {s.get("banidb_shabad_id") for s in banidb_seed_list}
        personal_banidb_ids = {self.shabads[sid].get("banidb_shabad_id") for sid in personal_seed_ids if sid in self.shabads}
        exclude_banidb = banidb_seed_ids | personal_banidb_ids

        personal_banidb_lookup = {
            s.get("banidb_shabad_id") for s in self.shabads.values() if s.get("banidb_shabad_id")
        }

        seen = {}
        for v in verses:
            sid = v.get("shabadId")
            if sid and sid not in seen and sid not in exclude_banidb and sid not in personal_banidb_lookup:
                seen[sid] = v

        candidates = []
        for sid in list(seen.keys())[:10]:
            shabad_data = matcher.get_shabad(sid)
            if not shabad_data:
                continue
            enrichment = matcher.extract_enrichment(shabad_data)

            translit = enrichment.get("transliteration") or ""
            title_words = translit.split()[:6]
            title = " ".join(title_words) if title_words else f"Ang {enrichment.get('ang_number', '?')}"
            shabad_obj = {
                "title": title,
                "banidb_shabad_id": sid,
                "sggs_raag": enrichment.get("sggs_raag"),
                "writer": enrichment.get("writer"),
                "ang_number": enrichment.get("ang_number"),
                "english_translation": enrichment.get("english_translation"),
                "transliteration": enrichment.get("transliteration"),
                "gurmukhi_text": enrichment.get("gurmukhi_text"),
            }
            candidates.append({
                "id": f"banidb_{sid}",
                "shabad": shabad_obj,
                "source": "banidb",
            })

        matcher.close()
        return candidates
