# Procedencia del portal

Copiado de [NebyX1/invest-lavalleja](https://github.com/NebyX1/invest-lavalleja), commit `ef5cca8faea55cd9f7883e220bec3d8ebec0fc3d`, el 1 de octubre de 2026.

Se mantienen las páginas editoriales, referencias, imágenes, documentos, catálogo, buscador, mapa territorial, dossier, wizard, SEO y navegación Astro. No se importaron el backend Flask ni el chatbot anterior.

El portal está dentro de `frontend/portal`. `npm run build` en `frontend` compila Astro y el cliente React/Vite existente y los ensambla en un sitio estático servido por Nginx. `/gianna/` aloja el mismo cliente mediante un iframe del mismo origen, con tema visual Invest. El iframe interno `/_gianna/` exige navegación desde esa página y no ofrece una entrada de chat independiente. El panel continúa en `/admin`.

El backend está separado y no sirve archivos del frontend. Conserva FastAPI, LangGraph, las herramientas, los modelos y el protocolo SSE. La conversación persiste sólo en el navegador. La nueva sesión firmada y los cupos por IP/navegador protegen el acceso y no almacenan mensajes.

Los reportes en `docs` son antecedentes del portal original. La validación actual está en `PRODUCTION-VALIDATION.md` en la raíz. Las pruebas originales de contenido y navegación se mantienen; las de Gianna cubren el agente que las reemplaza.
