import { apiUrl } from './api.js'

const ID_KEY = 'gianna-browser-v1'
export const QUOTA_KEY = 'gianna-quota-v1'
let browserId
let session
let pending

function identity() {
  if (browserId) return browserId
  try { browserId = localStorage.getItem(ID_KEY) } catch { /* Almacenamiento deshabilitado. */ }
  if (!/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(browserId || '')) browserId = crypto.randomUUID()
  try { localStorage.setItem(ID_KEY, browserId) } catch { /* La IP sigue protegida en el backend. */ }
  return browserId
}

async function connect() {
  const response = await fetch(apiUrl('/api/chat/session'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
    body: JSON.stringify({ browser_id: identity() }),
  })
  const result = await response.json()
  if (!response.ok) throw new Error(result.detail || 'No se pudo conectar con Gianna.')
  session = result
  return result
}

export async function ensureSession() {
  if (session) return session
  if (!pending) pending = connect().finally(() => { pending = null })
  return pending
}

export async function chatFetch(path, options = {}) {
  const { token } = await ensureSession()
  let response = await fetch(apiUrl(path), { ...options, method: 'POST', cache: 'no-store',
    headers: { ...options.headers, 'X-Chat-Session': token } })
  if (response.status === 401) {
    session = null
    const renewed = await ensureSession()
    response = await fetch(apiUrl(path), { ...options, method: 'POST', cache: 'no-store',
      headers: { ...options.headers, 'X-Chat-Session': renewed.token } })
  }
  return response
}

export function quotaFromResponse(response) {
  const remaining = response.headers.get('X-Chat-Remaining')
  const retry = response.headers.get('X-Chat-Retry-After') ?? response.headers.get('Retry-After')
  if (remaining === null && retry === null) return null
  return { remaining: Number(remaining ?? 0), retry_after: Number(retry ?? 0) }
}
