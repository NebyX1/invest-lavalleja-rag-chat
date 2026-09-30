import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

const Admin = lazy(() => import('./Admin.jsx'))
const isAdmin = /^\/admin(?:\/|$)/.test(window.location.pathname)

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {isAdmin ? <Suspense fallback={<div className="p-8">Cargando panel…</div>}><Admin /></Suspense> : <App />}
  </StrictMode>,
)
