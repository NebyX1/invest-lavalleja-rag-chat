#!/bin/sh
set -e

echo "Setting up Prometheus multiprocess directory at $PROMETHEUS_MULTIPROC_DIR"
rm -rf "$PROMETHEUS_MULTIPROC_DIR"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"

echo "Running database migrations..."
# Do not serve requests with a schema missing required tables.
# With set -e, a failed migration prevents this release from becoming healthy.
flask db upgrade

echo "Starting Gunicorn..."
exec gunicorn -c /app/gunicorn.conf.py "wsgi:app"
