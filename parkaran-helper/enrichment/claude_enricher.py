"""Extract themes, moods, and occasions from shabads using local LLM."""

import json
from llm.ollama_client import OllamaClient


class ThemeEnricher:
    def __init__(self):
        self.llm = OllamaClient()

    def extract_themes_batch(self, shabads):
        """
        Extract themes for a batch of shabads (max 12 at a time).
        Returns list of theme dicts in the same order.
        """
        shabad_texts = []
        for i, s in enumerate(shabads):
            text = f"{i + 1}. \"{s['title']}\""
            if s.get("transliteration"):
                text += f"\n   Transliteration: {s['transliteration'][:200]}"
            if s.get("english_translation"):
                text += f"\n   Translation: {s['english_translation'][:500]}"
            if s.get("sggs_raag"):
                text += f"\n   Raag: {s['sggs_raag']}"
            if s.get("writer"):
                text += f"\n   Writer: {s['writer']}"
            shabad_texts.append(text)

        prompt = f"""You are a Sikh Gurbani scholar. For each shabad below, analyze its spiritual meaning and provide structured metadata.

{chr(10).join(shabad_texts)}

For EACH shabad (numbered 1 to {len(shabads)}), return a JSON object with:
- "primary_theme": The main spiritual theme (e.g., "Surrender to Waheguru", "Detachment from Maya", "Love for the Guru", "Divine protection")
- "secondary_themes": Array of 2-3 additional themes
- "occasions": Array of Sikh occasions this shabad fits (from: "Anand Karaj", "Akhand Paath Bhog", "Gurpurab - Guru Nanak Dev Ji", "Gurpurab - Guru Gobind Singh Ji", "Vaisakhi", "Antim Ardas", "Sukhmani Sahib Paath", "Diwali/Bandi Chhor Divas", "General Diwan", "Amrit Sanchar", "Nagar Keertan")
- "mood": The emotional/spiritual mood (e.g., "Devotional longing", "Joyful praise", "Contemplative peace", "Urgent awakening")
- "brief_meaning": A 2-sentence summary accessible to someone learning about Sikhi

Return a JSON object with key "results" containing an array of objects, one per shabad, in order."""

        try:
            result = self.llm.generate_json(prompt, max_tokens=4000)
            themes = result.get("results", result) if isinstance(result, dict) else result
            if isinstance(themes, list):
                return themes
            return [None] * len(shabads)
        except (json.JSONDecodeError, Exception) as e:
            print(f"  Warning: Could not parse LLM response: {e}")
            return [None] * len(shabads)

    def disambiguate_match(self, user_title, candidates):
        """
        Use local LLM to pick the best BaniDB match for a shabad title.
        candidates: list of dicts with 'shabad_id', 'first_line', 'translation'.
        Returns the shabad_id of the best match, or None.
        """
        if not self.llm.is_available():
            return None

        candidate_text = "\n".join(
            f"{i + 1}. (ID: {c['shabad_id']}) {c['first_line']}\n   Translation: {c['translation'][:200]}"
            for i, c in enumerate(candidates)
        )

        prompt = f"""A Sikh keertan musician has a shabad titled: "{user_title}"

This is a romanized transliteration of a Gurbani shabad. Which of these shabads from the Guru Granth Sahib database is the best match?

{candidate_text}

If one clearly matches, return its ID number. If none match, return "none".
Return ONLY the shabad ID number or "none", nothing else."""

        try:
            answer = self.llm.generate(prompt, max_tokens=50)
            for c in candidates:
                if str(c["shabad_id"]) in answer:
                    return c["shabad_id"]
        except Exception:
            pass
        return None


# Backward compatibility alias
ClaudeEnricher = ThemeEnricher
