#!/usr/bin/env bash
# Levanta API + frontend compilado en http://localhost:8010 (Linux/macOS).
cd "$(dirname "$0")/backend"
exec ../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8010
