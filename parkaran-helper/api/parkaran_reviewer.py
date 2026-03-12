"""Review a parkaran for thematic flow and coherence."""

import json
import anthropic
import config


class ParkaranReviewer:
    def __init__(self, shabads_data):
        self.shabads = {s["id"]: s for s in shabads_data}
        self.claude = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def review(self, shabad_ids):
        """
        Review a full parkaran for thematic flow.
        Returns analysis with scores, transitions, and suggestions.
        """
        shabads = [self.shabads[sid] for sid in shabad_ids if sid in self.shabads]
        if len(shabads) < 2:
            return {"error": "Need at least 2 shabads to review a parkaran."}

        shabad_text = "\n\n".join(
            f"{i + 1}. \"{s['title']}\"\n"
            f"   Writer: {s.get('writer', 'N/A')} | Raag: {s.get('sggs_raag', 'N/A')} | Ang: {s.get('ang_number', 'N/A')}\n"
            f"   Translation: {(s.get('english_translation') or 'N/A')[:400]}\n"
            f"   Theme: {s.get('primary_theme', 'N/A')} | Mood: {s.get('mood', 'N/A')}"
            for i, s in enumerate(shabads)
        )

        prompt = f"""You are an expert in Sikh keertan parkaran (themed setlists). A great parkaran takes the listener on a spiritual journey — each shabad builds on the previous one's theme, creating a coherent bhaavanaa (spiritual feeling).

Here is a parkaran in the musician's intended performance order:

{shabad_text}

Analyze this parkaran and return ONLY valid JSON with these keys:

1. "overall_theme": What is the central theme? (1-2 sentences)
2. "flow_score": 1-10 rating of how well the theme flows
3. "transitions": Array of objects for each consecutive pair:
   - "from_title": Title of first shabad
   - "to_title": Title of second shabad
   - "rating": "strong", "moderate", or "weak"
   - "explanation": Why this transition works or doesn't (1-2 sentences using Gurbani concepts)
4. "strongest_moment": Object with "transition" (e.g., "2 → 3") and "explanation"
5. "weakest_moment": Object with "transition" and "explanation" and "suggestion" (what kind of shabad could bridge the gap)
6. "overall_assessment": 2-3 sentences on the parkaran as a whole — is the musician connecting on meaning or just on surface words?

No markdown formatting."""

        response = self.claude.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[: text.rfind("```")]
            text = text.strip()

        try:
            review = json.loads(text)
        except json.JSONDecodeError:
            review = {
                "overall_theme": "Unable to parse review.",
                "flow_score": 0,
                "transitions": [],
                "strongest_moment": {},
                "weakest_moment": {},
                "overall_assessment": text[:500],
            }

        # Add the shabad list for reference
        review["shabads"] = [
            {"id": s["id"], "title": s["title"], "keertani": s.get("keertani")}
            for s in shabads
        ]

        return review
