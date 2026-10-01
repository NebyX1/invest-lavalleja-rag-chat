#!/bin/sh
set -eu
if ! printf '%s' "$BACKEND_URL" | grep -Eq '^https?://[a-zA-Z0-9.-]+(:[0-9]+)?$'; then
  echo 'BACKEND_URL debe ser un origen http(s) sin ruta.' >&2
  exit 1
fi
if ! printf '%s' "$TRUSTED_PROXY_CIDR" | grep -Eq '^[0-9a-fA-F.:]+/[0-9]{1,3}$'; then
  echo 'TRUSTED_PROXY_CIDR debe ser el CIDR de la red del proxy.' >&2
  exit 1
fi
