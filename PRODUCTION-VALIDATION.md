# Validación del despliegue independiente

Ejecutada localmente el 1 de octubre de 2026, con Docker Desktop, Node 24 y Python 3.14 en contenedores.

## Resultados

| Comprobación | Resultado |
|---|---|
| Backend, administración, contrato SSE, cuotas, concurrencia y vencimiento | 26 pruebas aprobadas |
| Catálogo y persistencia del portal | 5 pruebas unitarias aprobadas |
| Portal, rutas, navegación, dossier, wizard, PDF, accesibilidad y Gianna, escritorio/móvil | 35 pruebas aprobadas |
| Contenedores separados, SSE del agente, herramientas, cookies, correo 2FA y CSRF por proxy/CORS | 8 pruebas aprobadas |
| Astro check / ESLint | 0 errores, 0 advertencias |
| npm audit, portal y agente | 0 vulnerabilidades después de actualizar Vitest a 4.1.11 |
| Build local y Docker del frontend | 32 páginas Astro y cliente React ensamblados |
| Build Docker del backend | Contexto independiente, sin frontend, Nginx, Node ni `.env` |
| Nginx | Configuración válida, sin buffering/caché SSE, acceso directo al iframe rechazado |
| Instalación vacía | Salud disponible, API administrativa privada, chat 503 con sesión válida, usuario UID 10001 |
| Persistencia | Cuenta, conocimiento y cupos sobreviven a reinicios |
| Salud de la instalación local | `ok=true`, `knowledge_ready=true`, 224 fragmentos |

La suite ordinaria omite ocho pruebas que necesitan el entorno aislado y una captura móvil duplicada. Las ocho pruebas de integración se ejecutaron aparte y aprobaron. Total: **74 pruebas aprobadas**, además de las comprobaciones de runtime.

## Cuotas y conversaciones

Se hicieron 20 consultas contra los contenedores de QA, ejecutando el grafo, recuperación real sobre la guía, herramientas y streaming. La consulta siguiente devolvió 429 y `Retry-After`. Se comprobó que una nueva sesión conserva el bloqueo por IP, que otra IP conserva el bloqueo de sesión y que Nginx reemplaza un `X-Forwarded-For` falsificado. Tras reiniciar el backend, el cupo siguió bloqueado.

Los tests con reloj controlado verificaron los 600 segundos completos desde la consulta número 20 y la reapertura exacta al vencer la espera. El navegador muestra la cuenta regresiva, bloquea los envíos, conserva el cupo al borrar/reabrir la conversación y vuelve a consultar al servidor al terminar la espera.

La base de cuotas sólo tiene `key`, `used`, `blocked_until` y `updated`. Los identificadores son hashes HMAC; ninguna tabla del servidor contiene conversaciones. Se retiraron los registros con consultas/argumentos y se deshabilitaron las trazas de conversaciones.

## Conexión con Ollama Cloud

Una consulta sintética al proveedor real, pasando por Nginx y el backend independiente, terminó sin eventos de error: respuesta de 1799 caracteres, primer token a los 2,85 segundos y duración total de 5,02 segundos. El resto de las pruebas de conversación usa respuestas controladas para evitar consumo adicional y resultados variables.

## Simulación de Coolify

Se ejecutaron cuatro servicios de QA en una red Docker independiente: backend Python, frontend Nginx con proxy, frontend Nginx con URL absoluta/CORS y un servicio local que simula Ollama y SMTP. El grafo, los modelos de recuperación, las herramientas y los endpoints administrativos fueron los reales. El SMTP de prueba entregó los códigos solamente en memoria dentro de ese entorno, sin correo externo.

Para reproducir, se necesita un índice local válido en `backend/index` y los modelos descargados en un volumen `invest-qa-models` con escritura para UID 10001:

```powershell
docker build -t invest-backend:production backend
docker build -t invest-frontend:production frontend
docker build --build-arg VITE_API_URL=http://127.0.0.1:18010 -t invest-frontend:cors-qa frontend
docker compose -p invest-coolify-qa -f backend/tests/deployment/compose.yaml up -d
$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:18080'
$env:DEPLOYMENT_TEST='true'
npm --prefix frontend/portal run test:e2e -- deployment.spec.ts --workers=1
```

Esperar `knowledge_ready=true` antes de lanzar la suite. Las pruebas ordinarias del portal y las de integración se ejecutan sucesivamente porque comparten la carpeta de reportes. La comprobación adicional de cupos está en `backend/tests/deployment/check_runtime.py`, para ejecutarla dentro del backend de QA. Usa un cupo nuevo y lo agota deliberadamente.

La simulación valida contenedores, red, proxy, CORS, variables, cookies, SSE, almacenamiento y reinicio. Los certificados HTTPS, nombres DNS y CIDR concretos de Coolify deben configurarse en el servidor real siguiendo `Admin-y-Coolify.md`; no se realizó un despliegue remoto.

## Pendientes externos

- **SMTP real:** los valores indicados por el usuario coinciden exactamente con el entorno del contenedor. Se verificó TLS en el puerto 465 desde Docker y desde el host; ambos recibieron **535** al autenticar. El servidor anuncia PLAIN y LOGIN. No se enviaron mensajes. El proveedor debe aceptar la cuenta/credencial para que funcione el 2FA real. El flujo de la aplicación pasó con el SMTP aislado.
- **Punto 2 de la solicitud:** quedó incompleto y requiere aclaración.

El código está validado para las correcciones especificadas. El correo real sigue pendiente antes de declarar listo el acceso administrativo de producción.
