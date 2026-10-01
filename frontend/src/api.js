// URL pública, sin claves. En blanco: /api a través de Nginx. URL absoluta: CORS.
const base = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
if (base && !/^https?:\/\/[^/?#]+$/.test(base)) throw new Error('VITE_API_URL debe ser un origen http(s), sin /api.')
export const apiUrl = (path) => `${base}${path}`
