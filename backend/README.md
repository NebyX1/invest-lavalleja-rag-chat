# Backend de Gianna

API Python autónoma: FastAPI, Uvicorn, LangGraph, Ollama Cloud, embeddings, reranker, LanceDB/NumPy y administración con 2FA. No sirve el frontend ni necesita Nginx.

[Arquitectura y flujos del sistema](../Arquitectura.md): API, agente, recuperación, cupos, administración e indexación.

Copiar `.env.example` a `.env` y configurar las variables antes de ejecutar:

```sh
docker compose up --build -d
```

O construir sólo esta carpeta:

```sh
docker build -t invest-backend .
```

Puerto interno 8010; salud `/api/health`. Montar un volumen persistente `/data` con UID/GID 10001. Usar un worker y una réplica para la activación del conocimiento existente. Configurar `CORS_ORIGINS` con el origen del frontend y `PROXY_TRUSTED_IPS` con la red exacta del proxy.

No persiste conversaciones. `chat-quota.sqlite3` conserva exclusivamente contadores por IP/sesión con hashes HMAC: 20 consultas aceptadas y 600 segundos de espera al agotarlas. SQLite también conserva la administración, sus sesiones y las versiones de documentos.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
python scripts/check_smtp.py
```

La comprobación SMTP valida TLS y autenticación sin enviar correo. Para uso local sin Docker, dejar las rutas de datos por defecto y usar `ADMIN_COOKIE_SECURE=false` sólo en HTTP local. Ver la [guía de despliegue](../Admin-y-Coolify.md).
