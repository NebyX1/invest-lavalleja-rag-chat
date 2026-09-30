#!/usr/bin/env bash
# Instala dependencias, construye el índice RAG y compila el frontend (Linux/macOS).
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { cp .env.example .env; echo "Se creó .env: completá OLLAMA_API_KEY y volvé a ejecutar."; exit 1; }
ls rag-data/*.docx >/dev/null 2>&1 || { echo "Falta el .docx en rag-data/ (ver Setup.md)."; exit 1; }

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r backend/requirements.txt
(cd backend && ../.venv/bin/python ingest.py)
(cd frontend && npm install && npm run build)
echo "Listo. Ejecutá ./start.sh"
