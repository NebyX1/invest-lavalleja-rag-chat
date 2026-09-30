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
# Cross-encoder multilingüe (mMARCO, incluye español) en ONNX cuantizado de ~118 MB
RERANK_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RERANK_FILE = "onnx/model_quint8_avx2.onnx"

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "https://ollama.com").rstrip("/")
# Ollama Cloud expone el modelo sin el sufijo ":cloud" cuando se llama directo a ollama.com
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").removesuffix(":cloud")

TOP_K = int(os.getenv("TOP_K", "8"))
# "lancedb" (en disco, por defecto) o "numpy" (todo en memoria, sin dependencias extra)
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "lancedb").strip().lower()
