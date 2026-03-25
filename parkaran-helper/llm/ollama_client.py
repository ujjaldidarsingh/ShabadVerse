"""Local LLM client using Ollama."""

import json
import ollama as _ollama
import config


class OllamaClient:
    def __init__(self, model=None):
        self.model = model or config.OLLAMA_MODEL
        self._client = _ollama.Client(host=config.OLLAMA_BASE_URL)

    def generate(self, prompt, max_tokens=3000):
        """Generate a response from the local LLM. Returns raw text."""
        response = self._client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={"num_predict": max_tokens},
            think=False,
        )
        return response.message.content.strip()

    def generate_json(self, prompt, max_tokens=3000):
        """Generate a JSON response from the local LLM. Returns parsed dict/list."""
        response = self._client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
            options={"num_predict": max_tokens},
            think=False,
        )
        text = response.message.content.strip()
        return json.loads(text)

    def is_available(self):
        """Check if Ollama is running and the model is available."""
        try:
            models = self._client.list()
            model_names = [m.model for m in models.models]
            return any(self.model in name for name in model_names)
        except Exception:
            return False
