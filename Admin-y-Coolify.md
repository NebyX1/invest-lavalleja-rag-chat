# Administración y despliegue de Gianna

El panel está en `/admin`. Gianna conserva FastAPI, LangGraph, Ollama Cloud, los modelos de embeddings y reranker, LanceDB/NumPy, la búsqueda híbrida y el protocolo SSE del chat. `sample-backend` se usó como referencia para contraseña con Argon2 y verificación por correo; su aplicación Flask no se incorporó al proyecto.

## Primer administrador

En un entorno local, instalá `backend/requirements.txt` en el entorno virtual existente y compilá el frontend con `npm ci` y `npm run build`. El backend carga `.env` de la raíz y después `backend/.env`, sin sobrescribir variables ya definidas. El entorno del contenedor siempre tiene prioridad.

Desde la raíz, usando el Python de tu entorno:

```powershell
# En esta máquina el entorno existente está en backend/venv.
& backend/venv/Scripts/python.exe backend/admin_cli.py create --email administrador@tu-dominio.uy
```

La herramienta pide la contraseña dos veces sin mostrarla. Para el entorno creado por `setup.ps1`, el ejecutable equivalente es `.venv/Scripts/python.exe`. En Linux es `.venv/bin/python`.

También se puede crear la primera cuenta mediante `ADMIN_EMAIL` y `ADMIN_PASSWORD`. Solo se usan si la tabla de administradores está vacía. Quitá `ADMIN_PASSWORD` del entorno después del primer arranque. Una cuenta existente no cambia de contraseña al redeployar.

Cada acceso requiere contraseña y un código de seis dígitos enviado al correo de la cuenta. El código vence en diez minutos, permite cinco intentos y se consume al verificarlo. El reenvío exige esperar un minuto y no reinicia el límite de intentos. No existe un acceso de desarrollo que omita el correo.

Las sesiones duran ocho horas por defecto, usan cookies HttpOnly y SameSite Strict, y pueden revocarse. Todas las escrituras requieren CSRF. En producción se exige una clave de al menos 32 caracteres y cookies Secure sobre HTTPS.

## Correo

El `.env` de `backend` admite las mismas variables SMTP que el ejemplo Flask:

```dotenv
MAIL_SERVER=smtp.tu-dominio.uy
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=usuario_smtp
MAIL_PASSWORD=clave_smtp
MAIL_DEFAULT_SENDER=Gianna <noreply@tu-dominio.uy>
```

Para SSL directo: puerto 465, `MAIL_USE_TLS=false`, `MAIL_USE_SSL=true`. No actives ambos. La validación del certificado permanece activa.

Podés comprobar conexión y credenciales sin enviar correo:

```powershell
& backend/venv/Scripts/python.exe scripts/check_smtp.py
```

Durante la validación del 30 de septiembre de 2026, el servidor configurado respondió pero rechazó las credenciales con `SMTPAuthenticationError`. Revisá usuario, contraseña y la habilitación del acceso SMTP en el proveedor. No se enviaron mensajes durante esa comprobación.

## Archivo para producción

El archivo preparado está en:

```text
rag-data/Invest_Lavalleja_Guia_de_Inversiones_2026.rag.jsonl
```

Es JSONL UTF-8 con una cabecera de versión `gianna.knowledge.v1` y un fragmento por línea. Cada fragmento conserva `section`, `text`, `zone`, `card` y `doc`. El catálogo se vuelve a derivar del texto validado. No se incluyen embeddings en el archivo: se calculan con el modelo que ya usa el sistema.

La conversión usa `build_chunks` y `build_overview` de la ingesta original. Se verificó igualdad exacta de 224 fragmentos, 129584 caracteres de contenido, 7 zonas, 16 fichas y del catálogo. Las secciones de anexos internos quedan excluidas. No se resumieron ni reescribieron los datos de la guía.

Para regenerarlo cuando cambie el Word:

```powershell
& backend/venv/Scripts/python.exe backend/knowledge_cli.py export `
  rag-data/Invest_Lavalleja_Guia_de_Inversiones_2026.docx `
  rag-data/Invest_Lavalleja_Guia_de_Inversiones_2026.rag.jsonl
```

El Word y el JSONL están fuera de Git y de la imagen Docker. Guardá una copia del JSONL para la carga inicial en producción. El panel también acepta el Word original y realiza esta misma conversión. Un JSONL arbitrario sin el esquema de Gianna se rechaza.

## Gestión de conocimiento

- **Cargar:** agrega una fuente y vectoriza la unión de los documentos activos.
- **Actualizar:** reemplaza una fuente en una nueva versión completa. El archivo anterior se elimina al finalizar correctamente.
- **Activar y desactivar:** incorpora o retira una fuente del índice, conservando el archivo cargado.
- **Eliminar documento:** lo retira del índice y borra su archivo. Las versiones que lo contienen dejan de poder restaurarse.
- **Reindexar:** reconstruye los vectores de las fuentes activas con los mismos modelos.
- **Vaciar base:** activa una base sin fragmentos. Conserva documentos e historial. Las nuevas consultas del chat reciben HTTP 503 hasta que se reactive conocimiento.
- **Restaurar versión:** activa un índice completo anterior, si sus documentos todavía existen.
- **Eliminar versión:** borra permanentemente su índice guardado. La versión activa no se puede eliminar. Se bloquea durante operaciones o consultas en curso.
- **Descargar:** entrega el JSONL normalizado de una fuente, solo a administradores autenticados.

Las cargas admiten un archivo de hasta 10 MiB. La base completa admite hasta 30000 fragmentos y 30 millones de caracteres. Los Word también tienen un límite de tamaño descomprimido para evitar archivos ZIP excesivos.

La indexación se ejecuta en un proceso separado. La base activa sigue disponible mientras se construye otra. Primero se validan la búsqueda y el catálogo; después se confirma el puntero activo en SQLite y se cambia el grafo que reciben las consultas nuevas. Cada conversación en streaming conserva el grafo y los títulos de la versión con la que comenzó.

Si una operación falla, la base anterior sigue activa y el panel muestra el fallo. Si el servicio se interrumpe, al arrancar marca esa operación como fallida y limpia las versiones sin confirmar. Las versiones confirmadas son inmutables y sobreviven a los reinicios.

En una instalación local con `backend/index`, el primer arranque adopta una copia de ese índice sin volver a vectorizar. No cambia sus fragmentos, vectores ni catálogo. A partir de ahí, las actualizaciones se hacen desde el panel; ejecutar la ingesta antigua sobre `backend/index` no reemplaza una versión administrada.

## Docker local

`Dockerfile` construye el frontend y el backend en una sola imagen. Las dependencias Python quedan fijadas en `backend/requirements.lock`, y las de Node en `frontend/package-lock.json`. No incorpora secretos, documentos, índices locales ni `sample-backend`.

Generá `ADMIN_SECRET_KEY` y guardalo en el `.env` de la raíz:

```powershell
& backend/venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Definí también la cuenta inicial, o creala mediante la consola del contenedor. Para iniciar en HTTP local:

```powershell
docker compose --env-file .env --env-file backend/.env `
  -f compose.yaml -f compose.local.yaml config -q

docker compose --env-file .env --env-file backend/.env `
  -f compose.yaml -f compose.local.yaml up --build -d
```

Abrí `http://localhost:8010/admin`. El override local publica el puerto únicamente en loopback y desactiva Secure para HTTP local. `compose.yaml` mantiene Secure como valor por defecto.

La primera instalación Docker arranca con una base vacía y el panel disponible. Ingresá y cargá el JSONL preparado. El contenedor descarga los modelos a su volumen en el primer uso. `/api/health` responde `ok=true` para permitir el acceso al panel y añade `knowledge_ready` para indicar si el chat puede consultar conocimiento.

## Coolify

1. Creá una aplicación desde este repositorio y seleccioná **Docker Compose**, con `compose.yaml` como archivo de definición.
2. Elegí un servidor Linux x86_64 compatible con AVX2, acorde al reranker existente. Reservá memoria para el chat y el proceso de ingesta concurrente; 3 GB es un punto de partida para esta guía, sujeto a la carga real.
3. Definí las variables de `.env.example` en Coolify: `OLLAMA_API_KEY`, `OLLAMA_MODEL`, `ADMIN_SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` y todas las variables `MAIL_*` necesarias.
4. Mantené `ADMIN_COOKIE_SECURE=true`. Definí `ADMIN_ALLOWED_ORIGINS=https://tu-dominio` y asigná al servicio `gianna` ese dominio con el puerto interno **8010**.
5. Definí `PROXY_TRUSTED_IPS=*` solo cuando el servicio sea accesible exclusivamente por la red privada del proxy de Coolify. `compose.yaml` no publica un puerto en el host.
6. Desplegá, ingresá en `https://tu-dominio/admin` y cargá el JSONL preparado. Esperá el estado **Completado** antes de comprobar el chat.
7. Quitá `ADMIN_PASSWORD` de las variables después de crear la primera cuenta y desplegá otra vez. La cuenta y su hash permanecen en el volumen.

La aplicación corre con UID/GID 10001 y un solo worker. Un bloqueo del volumen impide iniciar dos procesos escritores sobre el mismo estado. Mantené **una réplica**; desactivá cualquier despliegue que haga convivir dos réplicas sobre el mismo volumen. Esta restricción permite conservar el almacén embebido y el flujo del proyecto.

El volumen nombrado `gianna-data` se monta en `/data` y contiene:

| Ruta | Contenido |
|---|---|
| `/data/admin/admin.sqlite3` | Usuarios, sesiones, auditoría, trabajos y versión activa |
| `/data/admin/documents` | Archivos cargados y JSONL normalizados |
| `/data/admin/revisions` | Índices completos y sus catálogos |
| `/data/models` | Caché de embeddings y reranker |
| `/data/legacy-index` | Punto opcional para una migración manual del índice antiguo |

Configurá las copias de seguridad de ese volumen. No uses `docker compose down -v` para un reinicio normal: elimina el volumen. Para una copia coherente completa, detené el servicio y respaldá `/data`; luego volvé a iniciarlo. Restaurá el volumen con la misma `ADMIN_SECRET_KEY` y los permisos de UID/GID 10001.

La configuración sigue las opciones de [Docker Compose de Coolify](https://coolify.io/docs/applications/builds/docker-compose). Los checks de salud se definen en Compose y en la imagen.

## Recuperación de acceso

Desde la consola de Coolify, dentro del contenedor:

```bash
python admin_cli.py list
python admin_cli.py create --email administrador@tu-dominio.uy
python admin_cli.py reset-password --email administrador@tu-dominio.uy
```

Antes de usar `reset-password`, quitá `ADMIN_PASSWORD` del entorno para que la herramienta pida la nueva contraseña en forma interactiva. El restablecimiento revoca las sesiones de esa cuenta y vuelve a activarla. El siguiente acceso sigue exigiendo el código por correo.

## Validación

```powershell
& backend/venv/Scripts/python.exe -m pytest -q tests
```

La suite comprueba ambos factores, consumo único y vencimiento del código, límite de intentos y reenvío, CSRF, cookies, fallo de SMTP, cargas inválidas, aislamiento de descargas, reemplazo y unión de fuentes, vaciado persistente, restauración, eliminación, fallos de indexación, recuperación de trabajos y el protocolo SSE durante una activación concurrente.

La validación local pasó 19 pruebas. La imagen también se construyó y arrancó en Linux: se comprobaron el usuario sin privilegios, la API administrativa privada, el arranque con base vacía, la persistencia tras reiniciar y la búsqueda híbrida y el reranker sobre los 224 fragmentos reales. Actualizar una fuente inactiva conserva su estado; vuelve al corpus solo cuando se activa explícitamente.

Para comparar índices reales con el corpus privado, sin llamar al LLM:

```powershell
& backend/venv/Scripts/python.exe backend/knowledge_cli.py build `
  --output backend/admin-data/verificacion/index `
  rag-data/Invest_Lavalleja_Guia_de_Inversiones_2026.rag.jsonl

& backend/venv/Scripts/python.exe scripts/verify_rag.py `
  backend/index backend/admin-data/verificacion/index
```

Usá una carpeta de salida nueva. Se verificaron igualdad de vectores y catálogo, rankings idénticos en diez consultas, lookup por ficha/zona y filtros por zona. El workflow `.github/workflows/ci.yml` ejecuta pruebas, compila el frontend, construye la imagen y comprueba una instalación vacía sin secretos reales.
