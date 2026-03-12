"""Core parkaran builder: seed shabads → themed suggestions."""

import json
import anthropic
import config
from database.vector_store import ShabadVectorStore


class ParkaranBuilder:
    def __init__(self, shabads_data):
        self.shabads = {s["id"]: s for s in shabads_data}
        self.vector_store = ShabadVectorStore()
        self.claude = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def build(self, seed_ids, max_results=10, filters=None, banidb_seeds=None):
        """
        Given seed shabad IDs and/or BaniDB seeds, suggest connecting shabads.
        Returns dict with suggestions and flow explanation.
        """
        # Get personal DB seeds
        seeds = [self.shabads[sid] for sid in seed_ids if sid in self.shabads]

        # Add BaniDB seeds (already carry their own data)
        banidb_seed_list = banidb_seeds or []
        all_seeds = seeds + banidb_seed_list

        if not all_seeds:
            return {"error": "No valid seed shabads found"}

        # Build semantic query from all seeds
        query_parts = []
        for s in all_seeds:
            if s.get("primary_theme"):
                query_parts.append(s["primary_theme"])
            if s.get("secondary_themes"):
                query_parts.extend(s["secondary_themes"])
            if s.get("mood"):
                query_parts.append(s["mood"])
            if s.get("brief_meaning"):
                query_parts.append(s["brief_meaning"])
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

        # Semantic search in personal DB
        exclude = {str(sid) for sid in seed_ids}
        candidates = self.vector_store.search_similar(
            query_text, n_results=20, exclude_ids=exclude, where_filter=where_filter
        )

        # Enrich candidates with full data
        enriched_candidates = []
        for c in candidates:
            full = self.shabads.get(c["id"])
            if full:
                enriched_candidates.append({**c, "shabad": full, "source": "personal"})

        # If BaniDB seeds are present, also search BaniDB for thematic suggestions
        if banidb_seed_list:
            banidb_candidates = self._search_banidb_suggestions(all_seeds, seed_ids, banidb_seed_list)
            enriched_candidates.extend(banidb_candidates)

        if not enriched_candidates:
            return {"suggestions": [], "explanation": "No matching shabads found with the given filters."}

        # Use Claude to re-rank and explain connections
        return self._claude_rerank(all_seeds, enriched_candidates, max_results)

    def _search_banidb_suggestions(self, all_seeds, personal_seed_ids, banidb_seed_list):
        """Search BaniDB for thematic suggestions based on seed themes."""
        from enrichment.banidb_matcher import BaniDBMatcher

        # Extract keywords from seed themes for BaniDB search
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

        # Search BaniDB with top keywords (pick 2-3)
        search_terms = list(keywords)[:3]
        query = " ".join(search_terms)

        matcher = BaniDBMatcher()
        verses = matcher.search(query, searchtype=4)

        # Deduplicate and exclude seeds
        banidb_seed_ids = {s.get("banidb_shabad_id") for s in banidb_seed_list}
        personal_banidb_ids = {self.shabads[sid].get("banidb_shabad_id") for sid in personal_seed_ids if sid in self.shabads}
        exclude_banidb = banidb_seed_ids | personal_banidb_ids

        # Also exclude shabads already in personal DB (they'll be in vector results)
        personal_banidb_lookup = {
            s.get("banidb_shabad_id") for s in self.shabads.values() if s.get("banidb_shabad_id")
        }

        seen = {}
        for v in verses:
            sid = v.get("shabadId")
            if sid and sid not in seen and sid not in exclude_banidb and sid not in personal_banidb_lookup:
                seen[sid] = v

        # Fetch full shabad data for top results
        candidates = []
        for sid in list(seen.keys())[:10]:
            shabad_data = matcher.get_shabad(sid)
            if not shabad_data:
                continue
            enrichment = matcher.extract_enrichment(shabad_data)

            # Format as a candidate compatible with the existing pipeline
            # Use first ~6 words of transliteration as title
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

    def _claude_rerank(self, seeds, candidates, max_results):
        """Send seeds + candidates to Claude for re-ranking with explanations."""
        seed_text = "\n\n".join(
            f"Seed {i + 1}: \"{s.get('title', 'Unknown')}\"\n"
            f"  Translation: {(s.get('english_translation') or 'N/A')[:400]}\n"
            f"  Theme: {s.get('primary_theme', 'N/A')}\n"
            f"  Mood: {s.get('mood', 'N/A')}\n"
            f"  Raag: {s.get('sggs_raag', 'N/A')}, Writer: {s.get('writer', 'N/A')}"
            for i, s in enumerate(seeds)
        )

        candidate_text = "\n\n".join(
            f"Candidate {i + 1} (ID {c['id']}): \"{c['shabad'].get('title', 'Unknown')}\"\n"
            f"  Source: {c.get('source', 'personal').upper()}\n"
            f"  {'Keertani: ' + c['shabad'].get('keertani', 'N/A') if c.get('source') == 'personal' else ''}\n"
            f"  Translation: {(c['shabad'].get('english_translation') or 'N/A')[:300]}\n"
            f"  Theme: {c['shabad'].get('primary_theme', 'N/A')}\n"
            f"  Mood: {c['shabad'].get('mood', 'N/A')}\n"
            f"  Raag: {c['shabad'].get('sggs_raag', 'N/A')}"
            for i, c in enumerate(candidates[:15])
        )

        prompt = f"""You are an expert in Sikh keertan parkaran (themed setlists).

A parkaran creates a spiritual journey — shabads should connect thematically, building on each other's meanings to take the listener deeper into a specific bhaavanaa (spiritual feeling).

The musician has chosen these seed shabads:

{seed_text}

From their repertoire and the wider SGGS, these are potential connecting shabads:

{candidate_text}

For each candidate, provide:
1. "id": The candidate's ID (exactly as shown, e.g. "42" or "banidb_1234")
2. "connection_score": 1-10 rating of thematic connection to the seeds
3. "connection_explanation": 1-2 sentences explaining the thematic thread. Use Gurbani concepts (Naam, Hukam, Bhaanaa, Birha, Chardi Kala, etc.) where appropriate.
4. "suggested_position": Where in the parkaran ("opening", "building", "climax", "resolution")

Also provide:
5. "parkaran_theme": What overall theme/bhaavanaa does this parkaran explore?
6. "suggested_flow": Array of candidate IDs in recommended performance order (top {max_results} only)

Return ONLY valid JSON with keys: "candidates" (array), "parkaran_theme" (string), "suggested_flow" (array of IDs).
No markdown formatting."""

        response = self.claude.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[: text.rfind("```")]
            text = text.strip()

        # Build ID lookup for candidates
        candidate_lookup = {}
        for c in candidates:
            candidate_lookup[str(c["id"])] = c
            # Also map by integer if it's a number
            if isinstance(c["id"], int):
                candidate_lookup[c["id"]] = c

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: return candidates ordered by vector similarity
            return self._fallback_results(candidates, max_results)

        # Merge Claude's analysis with full shabad data
        claude_candidates = {}
        for c in result.get("candidates", []):
            cid = str(c.get("id", ""))
            claude_candidates[cid] = c

        suggestions = []
        for c in candidates:
            cid = str(c["id"])
            claude_data = claude_candidates.get(cid, {})
            if claude_data.get("connection_score", 0) < 3:
                continue

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
                "connection_score": claude_data.get("connection_score", 5),
                "connection_explanation": claude_data.get("connection_explanation", ""),
                "suggested_position": claude_data.get("suggested_position", "building"),
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

            suggestions.append(suggestion)

        suggestions.sort(key=lambda x: x["connection_score"], reverse=True)

        return {
            "suggestions": suggestions[:max_results],
            "parkaran_theme": result.get("parkaran_theme", ""),
            "suggested_flow": result.get("suggested_flow", []),
        }

    def _fallback_results(self, candidates, max_results):
        """Return candidates ordered by vector similarity when Claude fails."""
        return {
            "suggestions": [
                {
                    "id": c["id"],
                    "title": c["shabad"].get("title", "Unknown"),
                    "keertani": c["shabad"].get("keertani"),
                    "sggs_raag": c["shabad"].get("sggs_raag"),
                    "primary_theme": c["shabad"].get("primary_theme"),
                    "mood": c["shabad"].get("mood"),
                    "connection_score": round((1 - (c.get("distance") or 0.5)) * 10, 1),
                    "connection_explanation": "Thematically similar based on semantic analysis.",
                    "suggested_position": "building",
                    "source": c.get("source", "personal"),
                }
                for c in candidates[:max_results]
            ],
            "parkaran_theme": "Thematic connections found via semantic similarity.",
            "suggested_flow": [c["id"] for c in candidates[:max_results]],
        }
