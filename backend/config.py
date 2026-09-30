import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DOCX_PATH = ROOT / "rag-data" / "Invest_Lavalleja_Guia_de_Inversiones_2026.docx"
INDEX_DIR = ROOT / "backend" / "index"
MODEL_CACHE = ROOT / "backend" / ".model_cache"
FRONTEND_DIST = ROOT / "frontend" / "dist"

EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "https://ollama.com").rstrip("/")
# Ollama Cloud expone el modelo sin el sufijo ":cloud" cuando se llama directo a ollama.com
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").removesuffix(":cloud")

TOP_K = int(os.getenv("TOP_K", "8"))
