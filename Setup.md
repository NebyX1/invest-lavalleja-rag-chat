# Instalación

Para preparar el backend con entorno virtual, migraciones, datos base, nombres y roles, seguir [backend/Instructions.txt](backend/Instructions.txt). Incluye los comandos `python -m manage db upgrade -d migrations`, `seed-data`, `create-admin` y el arranque `python asgi.py`.

## Docker (recomendado)

Se necesita Docker con Compose v2.20 o superior. No se necesita Python ni Node en el host.

1. Copiar `backend/.env.example` a `backend/.env`.
2. Configurar `OLLAMA_API_KEY`, `OLLAMA_MODEL`, `ADMIN_SECRET_KEY`, cuenta inicial y SMTP. La clave debe tener al menos 32 caracteres y mantenerse entre despliegues.
3. Ejecutar desde la raíz:

```powershell
docker compose --env-file backend/.env -f compose.yaml -f compose.local.yaml config -q
docker compose --env-file backend/.env -f compose.yaml -f compose.local.yaml up --build -d
```

La web queda en `http://localhost:8080`; el backend en `http://localhost:8010`. El override local permite cookies sin Secure para HTTP y sólo publica puertos en loopback. En producción se mantienen cookies Secure y HTTPS.

Los scripts `setup.ps1`/`setup.sh` construyen las dos imágenes; `start.ps1`/`start.sh` inician los contenedores. Conservar el volumen `gianna-data` entre despliegues.

## Desarrollo sin contenedores

Python 3.14 (versión validada), Node 24 (mínimo 22.12). Instalar las dependencias de cada aplicación:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
npm ci --prefix frontend
npm ci --prefix frontend/portal
```

En `backend/.env`, usar rutas locales o dejar comentadas `ADMIN_DATA_DIR`, `INDEX_DIR` y `MODEL_CACHE`. Configurar `CORS_ORIGINS=http://127.0.0.1:4321,http://localhost:4321`, los mismos valores en `ADMIN_ALLOWED_ORIGINS` y `ADMIN_COOKIE_SECURE=false`.

Abrir tres terminales:

```powershell
# En backend/
.venv/Scripts/python -m uvicorn main:app --host 127.0.0.1 --port 8010
# En frontend/
npm run dev
# En frontend/portal/
npm run dev -- --host 127.0.0.1
```

Entrar por el portal Astro, normalmente `http://127.0.0.1:4321`. No abrir el cliente Vite como chat independiente.

## Guía de inversiones

Guardar los archivos internos en `backend/rag-data/`. No se versionan ni se incluyen en Docker. El panel acepta Word o JSONL con esquema `gianna.knowledge.v1` y excluye anexos internos.

Para convertir el documento original:

```powershell
backend/.venv/Scripts/python backend/knowledge_cli.py export backend/rag-data/Invest_Lavalleja_Guia_de_Inversiones_2026.docx backend/rag-data/Invest_Lavalleja_Guia_de_Inversiones_2026.rag.jsonl
```

Subir el resultado entrando por `/admin/login`, después de completar contraseña y código por correo. La API de salud indica `knowledge_ready=false` hasta activar conocimiento; el panel sigue disponible.
