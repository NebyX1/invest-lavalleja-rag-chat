# Frontend de Invest Lavalleja

Aplicación autónoma: portal Astro en `portal/`, cliente React/Vite de Gianna y administración en `src/`, Dockerfile y Nginx. No contiene credenciales del modelo ni SMTP.

[Arquitectura y flujos del sistema](../Arquitectura.md): compilación, navegación, chat, estado local y conexión con la API.

```sh
npm ci
npm ci --prefix portal
npm run build
docker build -t invest-frontend .
```

Configurar las variables de `.env.example`. `VITE_API_URL`, `PUBLIC_SITE_URL` y `PUBLIC_INDEXING` son argumentos de compilación. `BACKEND_URL` y `TRUSTED_PROXY_CIDR` se usan al ejecutar Nginx.

- API del mismo origen: `VITE_API_URL` vacío; Nginx envía `/api/` a `BACKEND_URL`.
- CORS directo: `VITE_API_URL` contiene el origen HTTPS del backend, sin `/api`.
- El chat se abre únicamente desde `/gianna/`; el login del panel está en `/admin/login` y la sesión autenticada en `/admin/`.
- El panel reconoce nombres y roles. Sólo los superadministradores administran usuarios y consultan auditoría; cada administrador puede cambiar su contraseña.
- El login presenta la Ventanilla Única de Inversiones de Lavalleja y solicita un captcha numérico, validado en el backend antes de enviar el código de acceso por correo.
- Las rutas desconocidas bajo `/admin/` devuelven 404.
- El historial se guarda en el navegador. Los cupos se validan en el backend.

El contexto Docker es esta carpeta. Se puede desplegar en Coolify sin incluir `backend/`. Ver la [guía de despliegue](../Admin-y-Coolify.md).
