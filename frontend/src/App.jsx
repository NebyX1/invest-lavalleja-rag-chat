import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'

const STORAGE_KEY = 'gianna-chat-v1'
const MAX_CHARS = 2000

const SUGGESTIONS = [
  '¿Por qué invertir en Lavalleja?',
  '¿Qué zonas hay para instalar mi proyecto?',
  '¿Qué ventajas fiscales tiene invertir acá?',
  'Quiero abrir un alojamiento turístico en las sierras',
  '¿Cuáles son los pasos para instalarme?',
]

const WELCOME =
  '¡Hola! Soy **Gianna**, la asesora de inversiones de **Invest Lavalleja**. Puedo orientarte sobre zonas, oportunidades, incentivos, permisos y los pasos para instalar tu proyecto en Lavalleja. ¿Qué querés hacer?'

function loadHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY))
    return Array.isArray(saved) ? saved : []
  } catch {
    return []
  }
}

async function* streamChat(messages, signal) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: messages.map(({ role, content }) => ({ role, content })) }),
    signal,
  })
  if (!res.ok) {
    let detail = 'Ocurrió un error. Probá de nuevo.'
    try {
      const j = await res.json()
      if (typeof j.detail === 'string') detail = j.detail
    } catch { /* respuesta sin JSON */ }
    throw new Error(detail)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const event = /^event: (.+)$/m.exec(raw)?.[1]
      const data = /^data: (.*)$/m.exec(raw)?.[1]
      if (event && data !== undefined) yield { event, data: JSON.parse(data) }
    }
  }
}

function Avatar() {
  return (
    <div className="avatar avatar-placeholder">
      <div className="bg-primary text-primary-content w-10 rounded-full">
        <span className="text-lg font-semibold">G</span>
      </div>
    </div>
  )
}

function Bubble({ msg, streaming }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`chat ${isUser ? 'chat-end' : 'chat-start'}`}>
      {!isUser && (
        <div className="chat-image">
          <Avatar />
        </div>
      )}
      <div
        className={`chat-bubble max-w-[85%] sm:max-w-[75%] ${
          isUser ? 'chat-bubble-primary' : 'bg-base-200 text-base-content'
        } ${msg.error ? 'chat-bubble-error' : ''}`}
      >
        {isUser ? (
          <span className="whitespace-pre-wrap">{msg.content}</span>
        ) : msg.content ? (
          <div className={`prose-chat ${streaming ? 'cursor' : ''}`}>
            <ReactMarkdown
              components={{ a: (p) => <a {...p} target="_blank" rel="noopener noreferrer" /> }}
            >
              {msg.content}
            </ReactMarkdown>
          </div>
        ) : (
          <span className="flex items-center gap-2 text-sm opacity-70">
            <span className="loading loading-dots loading-sm" />
            {msg.status}
          </span>
        )}
      </div>
      {!isUser && !streaming && (msg.tools?.length > 0 || msg.sources?.length > 0) && (
        <div className="chat-footer mt-1 flex flex-wrap items-center gap-1">
          {msg.tools?.map((t) => (
            <span key={t} className="badge badge-ghost badge-sm">
              {t}
            </span>
          ))}
          {msg.sources?.length > 0 && (
            <details className="text-xs opacity-70">
              <summary className="cursor-pointer select-none">Basado en la guía</summary>
              <ul className="mt-1 list-disc pl-4">
                {msg.sources.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [messages, setMessages] = useState(loadHistory)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const abortRef = useRef(null)
  const endRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-40)))
  }, [messages])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  const patchLast = (fn) =>
    setMessages((prev) => prev.map((m, i) => (i === prev.length - 1 ? fn(m) : m)))

  async function send(text) {
    const content = text.trim().slice(0, MAX_CHARS)
    if (!content || busy) return
    const history = [...messages.filter((m) => !m.error), { role: 'user', content }]
    setMessages([...history, { role: 'assistant', content: '' }])
    setInput('')
    setBusy(true)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      for await (const { event, data } of streamChat(history, ctrl.signal)) {
        if (event === 'token') patchLast((m) => ({ ...m, content: m.content + data }))
        else if (event === 'sources') patchLast((m) => ({ ...m, sources: data }))
        else if (event === 'status') patchLast((m) => ({ ...m, status: data }))
        else if (event === 'reset') patchLast((m) => ({ ...m, content: '' }))
        else if (event === 'tools') patchLast((m) => ({ ...m, tools: data }))
        else if (event === 'suggest') patchLast((m) => ({ ...m, suggestions: data }))
        else if (event === 'error') patchLast((m) => ({ ...m, content: data, error: true }))
      }
    } catch (e) {
      if (e.name === 'AbortError') patchLast((m) => (m.content ? m : { ...m, content: '_Respuesta detenida._' }))
      else patchLast((m) => ({ ...m, content: e.message || 'No pude conectarme.', error: true }))
    } finally {
      setBusy(false)
      abortRef.current = null
      inputRef.current?.focus()
    }
  }

  function reset() {
    abortRef.current?.abort()
    setMessages([])
    setBusy(false)
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(input)
    }
  }

  return (
    <div className="flex h-dvh flex-col bg-base-100">
      <header className="navbar border-b border-base-300 bg-base-100 px-4">
        <div className="flex flex-1 items-center gap-3">
          <Avatar />
          <div className="leading-tight">
            <h1 className="text-lg font-semibold">Gianna</h1>
            <p className="text-xs opacity-70">Asesora de inversiones · Invest Lavalleja</p>
          </div>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={reset} disabled={!messages.length}>
          Nueva conversación
        </button>
      </header>

      <main className="flex-1 overflow-y-auto px-3 py-4 sm:px-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-1">
          <Bubble msg={{ role: 'assistant', content: WELCOME }} />
          {messages.length === 0 && (
            <div className="mt-3 flex flex-wrap gap-2 pl-0 sm:pl-12">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="btn btn-outline btn-primary btn-sm h-auto py-1.5 font-normal" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          )}
          {messages.map((m, i) => (
            <Bubble key={i} msg={m} streaming={busy && i === messages.length - 1} />
          ))}
          {!busy && messages.at(-1)?.suggestions?.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-2 pl-0 sm:pl-12">
              {messages.at(-1).suggestions.map((s) => (
                <button key={s.label} className="btn btn-outline btn-primary btn-sm h-auto py-1.5 font-normal" onClick={() => send(s.text)}>
                  {s.label}
                </button>
              ))}
            </div>
          )}
          <div ref={endRef} />
        </div>
      </main>

      <footer className="border-t border-base-300 bg-base-100 px-3 py-3 sm:px-6">
        <form
          className="mx-auto flex max-w-3xl items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            send(input)
          }}
        >
          <textarea
            ref={inputRef}
            className="textarea textarea-bordered max-h-40 min-h-12 flex-1 resize-none"
            rows={1}
            maxLength={MAX_CHARS}
            placeholder="Escribí tu consulta sobre inversiones en Lavalleja…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            autoFocus
          />
          {busy ? (
            <button type="button" className="btn btn-neutral" onClick={() => abortRef.current?.abort()}>
              Detener
            </button>
          ) : (
            <button type="submit" className="btn btn-primary" disabled={!input.trim()}>
              Enviar
            </button>
          )}
        </form>
        <p className="mx-auto mt-2 max-w-3xl text-center text-xs opacity-60">
          Gianna orienta con información de la Guía de Inversiones 2026; no constituye asesoramiento financiero,
          legal ni una habilitación. Confirmá cada caso con el equipo de Invest Lavalleja.
        </p>
      </footer>
    </div>
  )
}
