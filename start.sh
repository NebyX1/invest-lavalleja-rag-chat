#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
docker compose --env-file backend/.env -f compose.yaml -f compose.local.yaml up -d
echo 'Invest Lavalleja: http://localhost:8080/gianna/'
