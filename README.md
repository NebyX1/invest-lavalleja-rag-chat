# Invest Lavalleja + Gianna

Portal original de Invest Lavalleja con el agente de inversiones existente: React/Vite, FastAPI, LangGraph, Ollama Cloud, embeddings multilingües, reranker y LanceDB/NumPy.

## Estructura

- **frontend/**: portal Astro en `portal/`, cliente React en `src/`, panel `/admin`, Dockerfile y Nginx. Su imagen no contiene Python ni credenciales.
- **backend/**: agente Python, API, administración, documentos locales, scripts, pruebas, Dockerfile y Uvicorn. Su imagen no contiene el frontend ni Nginx.
- `compose.yaml` reúne las dos configuraciones independientes para desarrollo y simulación local.

## Inicio local con Docker

Copiar `backend/.env.example` a `backend/.env`, configurar Ollama, una clave `ADMIN_SECRET_KEY` estable y SMTP. Los secretos se guardan sólo en el backend. En una instalación nueva se crea la cuenta con `ADMIN_EMAIL` y `ADMIN_PASSWORD`; retirar la contraseña del entorno después del primer arranque.

```powershell
docker compose --env-file backend/.env -f compose.yaml -f compose.local.yaml up --build -d
```

Web: [http://localhost:8080](http://localhost:8080). Gianna: `/gianna/`. Panel: `/admin`. API: `http://localhost:8010/api/health`.

Una instalación nueva inicia sin conocimiento. El administrador debe cargar la guía Word o su JSONL validado desde el panel. El índice existente se adopta si se monta en `/data/legacy-index`. Los modelos se descargan al volumen en el primer uso.

## Conversaciones y cupo

El historial vive únicamente en `localStorage` del navegador (`gianna-chat-v1`, últimos 40 mensajes). La API procesa el contexto durante cada solicitud y no persiste preguntas, respuestas ni argumentos de herramientas. No se usan checkpointers del grafo ni trazas de conversaciones. La inferencia mantiene el proveedor Ollama Cloud existente.

Cada consulta aceptada consume un cupo por **IP y sesión del navegador**. La número 20 inicia una espera de **600 segundos**. Durante esa espera la API devuelve 429 y `Retry-After`; la interfaz muestra la cuenta regresiva. Borrar el chat, abrir otra pestaña, reiniciar el backend o cambiar uno de los dos identificadores no elimina el otro límite. Las solicitudes inválidas o con la base vacía no consumen cupo; detener una respuesta ya aceptada sí lo consume.

`chat-quota.sqlite3` contiene exclusivamente hashes HMAC de identificadores, contadores y tiempos. No contiene conversaciones ni IPs en texto. Las entradas inactivas se eliminan después de 30 días. La base administrativa persiste cuentas, sesiones 2FA, documentos, versiones y auditoría administrativa.

Gianna se presenta dentro del portal. La ruta antigua `/chat/` redirige a `/gianna/`; el iframe interno no admite navegación directa ni incrustación en otro origen. La API exige el origen autorizado y una sesión firmada. Estas restricciones controlan el acceso desde navegadores; no constituyen autenticación de identidad contra clientes capaces de falsificar encabezados HTTP.

## Despliegue y desarrollo

[Arquitectura, tecnologías y flujos de frontend y backend](Arquitectura.md).

[Guía de Coolify y administración](Admin-y-Coolify.md). [Instalación y comandos](Setup.md).

Cada carpeta se puede construir sin acceso a la otra:

```powershell
docker build -t invest-frontend frontend
docker build -t invest-backend backend
```

La conexión admite proxy Nginx del mismo origen o `VITE_API_URL` absoluto con CORS y credenciales. El build del portal conserva las páginas, documentos, mapas, dossier, buscador y wizard originales. El agente mantiene sus herramientas, búsquedas, fuentes, streaming, cancelación y sugerencias.

## Validación

```powershell
python -m pip install -r backend/requirements-dev.txt
python -m pytest -q backend/tests
npm ci --prefix frontend
npm ci --prefix frontend/portal
npm --prefix frontend/portal run check
npm --prefix frontend/portal run lint
npm --prefix frontend/portal run test
npm --prefix frontend run build
$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:8080'
npm --prefix frontend/portal run test:e2e -- --workers=2
```

[Informe de validación de producción](PRODUCTION-VALIDATION.md).
