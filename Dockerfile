# syntax=docker/dockerfile:1
FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ADMIN_DATA_DIR=/data/admin MODEL_CACHE=/data/models INDEX_DIR=/data/legacy-index \
    ADMIN_COOKIE_SECURE=true OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
WORKDIR /app/backend
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 gianna && useradd --uid 10001 --gid gianna --no-create-home gianna \
    && mkdir -p /data/admin /data/models /data/legacy-index \
    && chown -R gianna:gianna /data
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
RUN mkdir -p /data/home && chown gianna:gianna /data/home && usermod --home /data/home gianna
COPY --chown=gianna:gianna backend/ ./
COPY --from=frontend /build/dist /app/frontend/dist
COPY --chmod=755 docker/entrypoint.sh /entrypoint.sh
USER gianna
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/api/health', timeout=4)"
ENTRYPOINT ["/entrypoint.sh"]
