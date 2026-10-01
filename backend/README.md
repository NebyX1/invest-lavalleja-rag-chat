# Backend de Gianna

API Python autónoma: FastAPI, Uvicorn, LangGraph, Ollama Cloud, embeddings, reranker, LanceDB/NumPy y administración con 2FA. No sirve el frontend ni necesita Nginx.

[Arquitectura y flujos del sistema](../Arquitectura.md): API, agente, recuperación, cupos, administración e indexación.

## Preparación y comandos

Ver [Instructions.txt](Instructions.txt). Desde la carpeta del backend:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Completar .env antes de continuar.
python -m manage db upgrade -d migrations
python -m manage seed-data
python -m manage create-admin "Nombre del admin" admin@tu-dominio.uy --super-admin
python asgi.py
```

El comando de alta también admite los argumentos del ejemplo:

```powershell
python -m manage create-admin "Nombre" correo@tu-dominio.uy contraseña-de-admin true
```

`true` crea un superadministrador; `false`, un administrador. El primer usuario debe ser superadministrador. Las migraciones SQL se versionan con `PRAGMA user_version`, se aplican también al inicializar las bases y preservan los datos existentes. Los administradores anteriores conservan sus permisos como superadministradores.

`seed-data` prepara las carpetas, la primera cuenta configurada por entorno y el índice previo, si existe. No genera contenido de inversión. Los comandos de migración y preparación requieren el backend detenido; la creación de cuentas puede hacerse con el servicio activo.

## Panel y permisos

El acceso web está en **`/admin/login` del frontend**; después de 2FA se usa `/admin/`. Un administrador gestiona conocimiento y su contraseña. Un superadministrador también crea cuentas, modifica roles y consulta auditoría. Cambiar un rol revoca las sesiones del usuario y siempre debe quedar un superadministrador activo.

El login requiere resolver un captcha numérico antes del envío del código por correo. El backend genera una suma, guarda el resultado con HMAC ligado a la sesión y consume el desafío en una transacción. Vence en cinco minutos; el formulario permite cambiar el cálculo y lo renueva tras un intento fallido. La respuesta no se incluye en el JSON de la sesión.

El backend publica únicamente la API. `/`, `/admin/login`, `/docs`, `/redoc` y `/openapi.json` devuelven 404; las rutas administrativas privadas requieren 2FA. Las rutas desconocidas bajo `/admin/` del frontend devuelven 404.

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
