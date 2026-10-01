import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")  # Las variables del contenedor tienen prioridad.

# La inferencia es transitoria; no exportar conversaciones a servicios de trazas.
os.environ["LANGCHAIN_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

DOCX_PATH = ROOT / "rag-data" / "Invest_Lavalleja_Guia_de_Inversiones_2026.docx"
INDEX_DIR = Path(os.getenv("INDEX_DIR", str(ROOT / "index")))
MODEL_CACHE = Path(os.getenv("MODEL_CACHE", str(ROOT / ".model_cache")))
ADMIN_DATA_DIR = Path(os.getenv("ADMIN_DATA_DIR", str(ROOT / "admin-data")))

# Orígenes exactos del portal, nunca '*'. La API no aloja una interfaz de chat.
CORS_ORIGINS = tuple(s.strip().rstrip("/") for s in os.getenv(
    "CORS_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080,http://localhost:4321,http://127.0.0.1:4321"
).split(",") if s.strip())
if not CORS_ORIGINS or any(not re_origin.startswith(("https://", "http://")) or
                           "/" in re_origin.split("://", 1)[1] or "*" in re_origin for re_origin in CORS_ORIGINS):
    raise ValueError("CORS_ORIGINS requiere orígenes http(s) exactos separados por comas.")

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
