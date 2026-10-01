# Coolify y administración

## Dos aplicaciones independientes

Crear **dos recursos Dockerfile** desde este repositorio. La configuración usa las opciones de [Dockerfile de Coolify](https://coolify.io/docs/applications/builds/dockerfile).

| Recurso | Base Directory / contexto | Dockerfile relativo | Puerto interno | Salud |
|---|---|---|---|---|
| Frontend | `/frontend` | `/Dockerfile` | 80 | `/health` |
| Backend | `/backend` | `/Dockerfile` | 8010 | `/api/health` |

Ambas imágenes se construyen usando únicamente su propia carpeta. Los Compose dentro de cada carpeta también permiten desplegarlas por separado. El Compose de la raíz sirve para simular ambos recursos juntos; utiliza `include` y requiere Compose >=2.20.

### Backend

Definir **variables de ejecución** de `backend/.env.example`. Como mínimo: `OLLAMA_API_KEY`, `OLLAMA_MODEL`, `ADMIN_SECRET_KEY` (32+ caracteres), `CORS_ORIGINS` y las variables SMTP. Para la cuenta inicial, agregar `ADMIN_EMAIL` y `ADMIN_PASSWORD` y retirar esta última después de crear la cuenta.

- `CORS_ORIGINS=https://invest.tu-dominio.uy`: origen exacto del frontend, sin barra final. Múltiples orígenes separados por comas; no admite `*`.
- `ADMIN_ALLOWED_ORIGINS`: los mismos orígenes del frontend para CSRF administrativo.
- `ADMIN_COOKIE_SECURE=true`, `ADMIN_COOKIE_SAMESITE=strict`.
- Montar un volumen persistente completo en **`/data`**, con escritura para **UID/GID 10001**. Incluye `/data/admin`, `/data/models`, `/data/legacy-index` y `/data/home`.
- `PROXY_TRUSTED_IPS`: IPs o CIDR exactos del proxy que conecta a Uvicorn. Si el frontend usa proxy Nginx, confiar en su red privada. Es necesario para identificar la IP real y aplicar el cupo correctamente. No publicar el puerto 8010 sin protección del proxy en producción.
- Mantener **un worker y una réplica**: el sistema existente activa índices en memoria y protege su volumen mediante `runtime.lock`. Reservar unos 3 GB iniciales para agente e ingesta, ajustar según carga. Servidor Linux x86_64 con AVX2 para el reranker existente.

El backend arranca con Uvicorn, sin Nginx, Node ni archivos del sitio. Una base vacía permite iniciar el panel; cargar la guía antes de habilitar consultas.

### Frontend: conexión mediante proxy

Configuración recomendada para cookies y streaming:

- **Build**: `VITE_API_URL` vacío; `PUBLIC_SITE_URL=https://invest.tu-dominio.uy` para URL canónica y sitemap; `PUBLIC_INDEXING=true` para permitir indexación pública.
- **Ejecución**: `BACKEND_URL=http://nombre-del-backend:8010` si ambos recursos comparten red Docker, o el dominio HTTPS del backend. Usar el nombre DNS real asignado al recurso, no asumir que se llama `backend` en Coolify.
- `TRUSTED_PROXY_CIDR`: CIDR exacto de la red del proxy de Coolify que llega a Nginx. Nginx obtiene la IP del cliente de ese proxy y reemplaza `X-Forwarded-For` antes de enviarlo al backend.
- Asignar el dominio público al puerto **80**. Configurar HTTPS en Coolify.

Nginx sirve Astro y React, envía `/api/*` al backend y desactiva buffering y caché del streaming SSE. La salud `/health` comprueba el frontend; `/api/health` comprueba la conexión completa.

### Frontend: conexión CORS directa

También se admite el patrón del frontend del Buzón Ciudadano:

- **Build**: `VITE_API_URL=https://api.invest.tu-dominio.uy`, sin `/api` ni barra final. Reconstruir la imagen al cambiar este valor; Vite lo incorpora al JavaScript.
- **Backend**: `CORS_ORIGINS` y `ADMIN_ALLOWED_ORIGINS` contienen el dominio del frontend; los métodos, encabezados de sesión/CSRF y credenciales están habilitados explícitamente.
- Frontend y backend deben usar HTTPS. Para cookies administrativas Strict, usar dominios del mismo sitio, por ejemplo `invest.ejemplo.uy` y `api.invest.ejemplo.uy`.
- Para sitios distintos, se puede configurar `ADMIN_COOKIE_SAMESITE=none` con `ADMIN_COOKIE_SECURE=true`, sujeto a las restricciones del navegador para cookies de terceros. El proxy del mismo origen evita esa dependencia.

La API comprueba el origen y la sesión firmada incluso cuando el navegador permite CORS. El historial no se envía a ningún endpoint de guardado.

## Administración

`/admin/login` identifica la Ventanilla Única de Inversiones de Lavalleja. Exige contraseña, captcha numérico validado por el backend y código por correo; después de verificar se accede a `/admin/`. El captcha es una suma, está ligado a la sesión, vence en cinco minutos y se consume en cada intento. Se puede solicitar otro cálculo desde el formulario. El código por correo es válido durante 10 minutos, admite cinco intentos y un único uso. El reenvío espera un minuto y no reinicia intentos. Sesiones revocables de ocho horas por defecto, cookies HttpOnly y CSRF en escrituras.

Los administradores gestionan conocimiento y su contraseña; los superadministradores también gestionan cuentas, roles y auditoría. El primer usuario debe ser superadministrador. Las cuentas anteriores mantienen permisos mediante la migración a superadministrador.

Para crear una cuenta desde el contenedor del backend:

```sh
python -m manage create-admin "Nombre del admin" administrador@tu-dominio.uy --super-admin
```

La consola solicita la contraseña sin mostrarla. El panel gestiona carga, actualización, activación, eliminación, reindexación y restauración de versiones. Admite archivos hasta 10 MiB. Los índices confirmados sobreviven a reinicios; un fallo de ingesta mantiene la versión anterior. Ninguna tabla guarda conversaciones.

Los comandos de migración y datos base se describen en [backend/Instructions.txt](backend/Instructions.txt). El backend admite comandos pasados a su contenedor. Para migrar manualmente, detener el servicio y ejecutar `docker compose run --rm backend python -m manage db upgrade -d migrations`; el arranque también aplica las migraciones pendientes. La migración conserva los datos y los cupos.

El backend devuelve 404 en `/`, `/admin/login`, `/docs`, `/redoc` y `/openapi.json`. Las rutas `/admin/*` desconocidas del frontend también devuelven 404.

SMTP admite TLS en 587 o SSL en 465. No activar ambos. Para revisar conexión y autenticación sin enviar correo:

```sh
python scripts/check_smtp.py
```

No hay modo de acceso que omita 2FA. Las pruebas automatizadas usan un servicio SMTP local aislado; las credenciales del proveedor real deben validarse en el entorno de despliegue.

## Simulación local

```powershell
docker compose --env-file backend/.env -f compose.yaml -f compose.local.yaml up --build -d
docker compose --env-file backend/.env -f compose.yaml -f compose.local.yaml ps
```

Abrir `http://localhost:8080/gianna/` y `/admin/login`. El backend está en otro contenedor, en el puerto 8010. La simulación usa HTTP en loopback; Coolify proporciona certificados y proxy HTTPS reales.

[Resultados y alcance de las pruebas](PRODUCTION-VALIDATION.md).

## Referencias revisadas

- [Backend del Buzón Ciudadano](https://github.com/IntendenciaDeLavalleja/buzon-ciudadano-backend): imagen Python autónoma, entrypoint y comprobación de salud.
- [Comandos y rutas del backend de referencia](https://github.com/NebyX1/buzon-ciudadano-backend): entorno virtual, migración, datos base, alta de administrador con nombre y rol, y entrada administrativa explícita.
- [Frontend del Buzón Ciudadano](https://github.com/IntendenciaDeLavalleja/buzon-ciudadano-frontend): build Node separado del runtime Nginx, URL pública de la API en compilación y credenciales del navegador.

Se adaptaron estos patrones a FastAPI y al agente existente; se conservaron sus tecnologías.
