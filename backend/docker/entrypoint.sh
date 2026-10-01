#!/bin/sh
set -eu
if [ -z "${OLLAMA_API_KEY:-}" ] || [ -z "${OLLAMA_MODEL:-}" ]; then
  echo "Faltan OLLAMA_API_KEY y/o OLLAMA_MODEL." >&2
  exit 1
fi
if [ "${ADMIN_COOKIE_SECURE:-true}" = "true" ] && [ -z "${ADMIN_SECRET_KEY:-}" ]; then
  echo "Configurá ADMIN_SECRET_KEY (al menos 32 caracteres) para producción." >&2
  exit 1
fi
for directory in "$ADMIN_DATA_DIR" "$MODEL_CACHE"; do
  if [ ! -w "$directory" ]; then
    echo "El volumen persistente no permite escribir en $directory (UID 10001)." >&2
    exit 1
  fi
done
exec python -m uvicorn main:app --host 0.0.0.0 --port 8010 --workers 1 \
  --proxy-headers --forwarded-allow-ips "${PROXY_TRUSTED_IPS:-127.0.0.1}"
