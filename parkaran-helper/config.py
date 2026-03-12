import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")

BANIDB_BASE_URL = "https://api.banidb.com/v2"
BANIDB_SEARCH_TYPE = 1  # First letter (start) — default for discover/builder
BANIDB_SOURCE = "G"  # Sri Guru Granth Sahib Ji

BASE_DIR = os.path.dirname(__file__)
EXCEL_PATH = os.path.join(BASE_DIR, "..", "Keertan Track Database.xlsx")
DATA_DIR = os.path.join(BASE_DIR, "data")
CHROMA_DB_PATH = os.path.join(DATA_DIR, "chroma_db")
ENRICHED_DATA_PATH = os.path.join(DATA_DIR, "enriched_shabads.json")
CACHE_DB_PATH = os.path.join(DATA_DIR, "shabad_cache.db")

VOYAGE_MODEL = "voyage-3.5-lite"
CLAUDE_MODEL = "claude-sonnet-4-20250514"
