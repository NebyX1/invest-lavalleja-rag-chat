# Setup

Guía para levantar **Gianna** desde cero en cualquier máquina.

## Requisitos

| Herramienta | Versión | Nota |
|---|---|---|
| Python | 3.11 o superior | Probado con 3.11 |
| Node.js | 20.19+ o 22.12+ | Solo para compilar el frontend |
| Clave de Ollama Cloud | – | Crear en <https://ollama.com/settings/keys> |
| Documento de la guía | `.docx` | Ver paso 3 |

No hace falta GPU. La primera ejecución descarga el modelo de embeddings (~220 MB) y, al arrancar el servidor, el reranker (~118 MB); ambos necesitan conexión a internet y quedan en `backend/.model_cache/`.

## Inicio rápido

### 1. Clonar

```bash
git clone https://github.com/NebyX1/invest-lavalleja-rag-chat.git
cd invest-lavalleja-rag-chat
```

### 2. Configurar el entorno

```bash
cp .env.example .env        # Windows: Copy-Item .env.example .env
```

Editá `.env` y completá tu clave:

```env
OLLAMA_API_KEY=tu_clave_de_ollama_aqui
OLLAMA_MODEL=deepseek-v4.1-flash:cloud
```

`OLLAMA_MODEL` acepta el sufijo `:cloud`, que se ignora al llamar a `ollama.com`. El modelo debe soportar *tool calling*.

### 3. Colocar el documento fuente

Copiá el Word con la guía en la carpeta `rag-data/`, con este nombre exacto:

```text
rag-data/Invest_Lavalleja_Guia_de_Inversiones_2026.docx
```

El documento no se versiona en el repositorio porque incluye anexos de uso interno. Si usás otro nombre, cambiá `DOCX_PATH` en `backend/config.py`.

### 4. Instalar y construir

**Windows (PowerShell):**

```powershell
.\setup.ps1
```

**Linux / macOS:**

```bash
chmod +x setup.sh start.sh
./setup.sh
```

El script hace, en orden:

1. Crea el entorno virtual `.venv` e instala `backend/requirements.txt` (incluye LanceDB).
2. Ejecuta `backend/ingest.py`: lee el `.docx`, genera los chunks, calcula los embeddings y el catálogo, y crea la tabla LanceDB (`backend/index/`).
3. Instala las dependencias del frontend y lo compila (`frontend/dist/`).

### 5. Arrancar

```powershell
.\start.ps1      # Windows
```

```bash
./start.sh       # Linux / macOS
```

Abrí <http://localhost:8010>. Para comprobar que el backend está sano:

```bash
curl http://localhost:8010/api/health
# {"ok":true,"model":"deepseek-v4.1-flash","chunks":155}
```

## Comandos manuales (equivalentes al script)

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt      # Windows: .venv\Scripts\pip
cd backend && ../.venv/bin/python ingest.py && cd ..
cd frontend && npm install && npm run build && cd ..
cd backend && ../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

## Variables de entorno

| Variable | Obligatoria | Por defecto | Descripción |
|---|---|---|---|
| `OLLAMA_API_KEY` | Sí | – | Clave de Ollama Cloud |
| `OLLAMA_MODEL` | Sí | – | Modelo (con o sin `:cloud`) |
| `OLLAMA_HOST` | No | `https://ollama.com` | Endpoint de Ollama |
| `TOP_K` | No | `8` | Fragmentos recuperados por consulta |
| `VECTOR_BACKEND` | No | `lancedb` | `lancedb` (en disco) o `numpy` (todo en memoria) |

## Tareas habituales

**Actualizar el documento:** reemplazá el `.docx`, ejecutá `cd backend && ../.venv/bin/python ingest.py` y reiniciá el servidor.

**Cambiar el almacén vectorial:** el modo por defecto es LanceDB. Para usar la alternativa en memoria, agregá `VECTOR_BACKEND=numpy` al `.env` y reiniciá (no requiere reindexar). Para comparar ambos: `python scripts/compare_backends.py`.

**Desarrollar el frontend con recarga en caliente:** con el backend corriendo en el puerto 8010,

```bash
cd frontend
npm run dev        # http://localhost:5173, con proxy /api → 8010
```

**Probar el agente por consola** (con el servidor levantado; cada argumento es un turno):

```bash
.venv/bin/python scripts/ask.py "Tengo 100 mil dólares, qué me conviene en el norte?" "Compará las dos primeras"
```

La salida muestra el estado, las herramientas usadas y la respuesta.

**Reranker (segunda oportunidad del agente):** viene activado y no requiere configuración ni variables de entorno. Usa `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingüe, con español) en ONNX cuantizado y CPU, y el LLM lo invoca con la herramienta `buscar_guia_reranker` cuando la primera búsqueda no alcanza. El modelo se descarga en el primer arranque del servidor, así que ese arranque tarda más. Para probarlo, con el servidor levantado:

```bash
.venv/bin/python scripts/ask.py "¿Qué permisos necesito para una cámara de frío?"
```

Si el LLM lo usó, la salida lista `búsqueda refinada con reranker` entre las herramientas y el servidor imprime la llamada en `tools:`. Para cambiar de modelo, editar `RERANK_MODEL` y `RERANK_FILE` en `backend/config.py` (debe ser un cross-encoder con ONNX y `tokenizer.json`; ver la sección 5.2 de [Arquitectura.md](Arquitectura.md)).

**Cambiar de puerto:** editá `--port` en `start.ps1` / `start.sh`. Si usás el modo desarrollo del frontend, ajustá también el proxy en `frontend/vite.config.js`.

## Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| `Faltan OLLAMA_API_KEY u OLLAMA_MODEL en .env` | El `.env` no existe o está vacío (ver paso 2) |
| `No pude conectarme con el modelo` en el chat | Clave inválida, modelo inexistente o sin internet. Revisá la consola del servidor: imprime `Agent error: …` |
| `No se encuentra …docx` al indexar | El documento no está en `rag-data/` con el nombre esperado |
| `FileNotFoundError: index/chunks.json` al arrancar | Falta ejecutar la ingesta (`setup`) |
| Error de puerto en uso | Cambiá el puerto de `start.*` (el 8000 suele estar ocupado por otros servicios) |
| Aviso de *symlinks* de Hugging Face en Windows | Inofensivo; el modelo se descarga igual |
| El primer arranque del servidor tarda o parece colgado | Está descargando y precargando el reranker (~118 MB). Esperar a `Application startup complete`; los siguientes arranques son rápidos |
| El reranker falla al cargar en ARM u otra arquitectura | Cambiar `RERANK_FILE` en `backend/config.py` por otra variante ONNX del mismo modelo (p. ej. `onnx/model_qint8_arm64.onnx`) |
| `pip` termina con código 1 por un aviso de actualización | Inofensivo; es un aviso de versión de pip |
| Respuestas viejas en el navegador tras actualizar | Usá "Nueva conversación" o recargá con `Ctrl+F5` |

## Qué no se sube a git

`.env`, `.venv/`, `node_modules/`, `frontend/dist/`, `backend/index/`, `backend/.model_cache/` y el `.docx` de `rag-data/` están en `.gitignore`. Los artefactos se recrean con el setup.

## Siguiente lectura

[Arquitectura.md](Arquitectura.md) explica el funcionamiento interno: ingesta, recuperación híbrida, agente LangGraph, herramientas y protocolo de streaming.
