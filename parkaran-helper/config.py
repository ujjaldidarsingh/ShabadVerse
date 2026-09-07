import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)

# Ollama local LLM
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:14b")

BANIDB_BASE_URL = "https://api.banidb.com/v2"
BANIDB_SEARCH_TYPE = 0  # First letters from the start of a line
BANIDB_SOURCE = "G"  # Sri Guru Granth Sahib Ji

BASE_DIR = os.path.dirname(__file__)
EXCEL_PATH = os.path.join(BASE_DIR, "..", "Keertan Track Database.xlsx")
DATA_DIR = os.path.abspath(os.getenv("SHABADVERSE_DATA_DIR", os.path.join(BASE_DIR, "data")))
CHROMA_DB_PATH = os.path.join(DATA_DIR, "chroma_db")
ENRICHED_DATA_PATH = os.path.join(DATA_DIR, "enriched_shabads.json")
CACHE_DB_PATH = os.path.join(DATA_DIR, "shabad_cache.db")

# Local embedding model (ChromaDB built-in ONNX export of all-MiniLM-L6-v2)
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# ChromaDB collection names
PERSONAL_COLLECTION_NAME = "shabads"
SGGS_COLLECTION_NAME = "sggs_shabads"
# One vector per verse (tuk) rather than per shabad. Powers "match by line",
# where the unit of meaning is the single line, not the whole shabad.
SGGS_LINES_COLLECTION_NAME = "sggs_lines"

# SGGS data
SGGS_DATA_PATH = os.path.join(DATA_DIR, "sggs_all_shabads.json")
