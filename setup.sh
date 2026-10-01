#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f backend/.env ]; then
    cp backend/.env.example backend/.env
    echo 'Se creó backend/.env. Configurá Ollama, ADMIN_SECRET_KEY y SMTP.'
    exit 1
fi
docker compose --env-file backend/.env -f compose.yaml -f compose.local.yaml build
echo 'Imágenes listas. Ejecutá ./start.sh'
