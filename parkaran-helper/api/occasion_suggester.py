"""Suggest shabads for specific Sikh occasions."""

from database.vector_store import ShabadVectorStore

OCCASIONS = {
    "anand_karaj": {
        "name": "Anand Karaj (Wedding)",
        "description": "Sikh wedding ceremony celebrating the union of two souls with Waheguru",
        "themes": "Divine love, union with Waheguru, marriage blessings, Laavan, joy of spiritual union, companionship on the path",
        "icon": "rings",
    },
    "akhand_paath_bhog": {
        "name": "Akhand Paath Bhog",
        "description": "Completion of a continuous reading of Sri Guru Granth Sahib Ji",
        "themes": "Gratitude to Waheguru, praise of the Guru, completion, spiritual fulfillment, Anand, blessings received through Bani",
        "icon": "book",
    },
    "gurpurab_nanak": {
        "name": "Guru Nanak Dev Ji Gurpurab",
        "description": "Celebration of the birth/legacy of Guru Nanak Dev Ji",
        "themes": "Guru Nanak's teachings, Naam Simran, equality of all, Ik Onkar, divine light, truth and compassion, Jap Ji concepts",
        "icon": "sun",
    },
    "gurpurab_gobind": {
        "name": "Guru Gobind Singh Ji Gurpurab",
        "description": "Celebration of the birth/legacy of Guru Gobind Singh Ji",
        "themes": "Khalsa, courage, sacrifice, Chardi Kala, warrior saint, Amrit, fearlessness, standing for truth",
        "icon": "shield",
    },
    "vaisakhi": {
        "name": "Vaisakhi",
        "description": "Celebration of the creation of the Khalsa Panth",
        "themes": "Khalsa creation, Amrit, sacrifice, Panj Pyare, new beginning, devotion, courage, community",
        "icon": "flag",
    },
    "antim_ardas": {
        "name": "Antim Ardas / Bhog",
        "description": "Final prayers and kirtan for a departed soul",
        "themes": "Impermanence of life, acceptance of Hukam, soul's journey to Waheguru, detachment from Maya, comfort in Naam, peace",
        "icon": "dove",
    },
    "sukhmani_sahib": {
        "name": "Sukhmani Sahib Paath",
        "description": "Gathering around the recitation of Sukhmani Sahib",
        "themes": "Peace of mind, Naam Simran, spiritual healing, contentment, surrender, serenity, removing anxiety",
        "icon": "heart",
    },
    "diwali_bandi_chhor": {
        "name": "Diwali / Bandi Chhor Divas",
        "description": "Celebration of Guru Hargobind Sahib Ji's release from Gwalior Fort",
        "themes": "Liberation, freedom, light over darkness, divine justice, Guru's grace, celebration, Chardi Kala",
        "icon": "lamp",
    },
    "general_diwan": {
        "name": "General Diwan / Samagam",
        "description": "Regular congregational kirtan gathering",
        "themes": "Praise of Waheguru, devotion, Naam, Guru's blessings, sangat, spiritual awakening, love for the divine",
        "icon": "music",
    },
    "amrit_sanchar": {
        "name": "Amrit Sanchar",
        "description": "Sikh initiation ceremony",
        "themes": "Amrit, commitment to Sikhi, Khalsa identity, courage, devotion to Guru, new spiritual birth, discipline",
        "icon": "droplet",
    },
}


class OccasionSuggester:
    def __init__(self, shabads_data):
        self.shabads = {s["id"]: s for s in shabads_data}
        self.vector_store = ShabadVectorStore()

    def get_occasions(self):
        """Return list of available occasions."""
        return [
            {"id": key, **{k: v for k, v in val.items() if k != "themes"}}
            for key, val in OCCASIONS.items()
        ]

    def suggest(self, occasion_id, count=10, keertani=None):
        """Suggest shabads for a given occasion."""
        occasion = OCCASIONS.get(occasion_id)
        if not occasion:
            return {"error": f"Unknown occasion: {occasion_id}"}

        where_filter = None
        if keertani:
            where_filter = {"keertani": keertani}

        candidates = self.vector_store.search_similar(
            occasion["themes"],
            n_results=count,
            where_filter=where_filter,
        )

        suggestions = []
        for c in candidates:
            full = self.shabads.get(c["id"])
            if not full:
                continue
            suggestions.append({
                "id": c["id"],
                "title": full["title"],
                "keertani": full.get("keertani"),
                "sggs_raag": full.get("sggs_raag"),
                "performance_raag": full.get("performance_raag"),
                "ang_number": full.get("ang_number"),
                "writer": full.get("writer"),
                "primary_theme": full.get("primary_theme"),
                "mood": full.get("mood"),
                "brief_meaning": full.get("brief_meaning"),
                "link": full.get("link"),
                "relevance": round((1 - (c.get("distance") or 0.5)) * 10, 1),
            })

        return {
            "occasion": {
                "id": occasion_id,
                "name": occasion["name"],
                "description": occasion["description"],
            },
            "suggestions": suggestions,
        }
