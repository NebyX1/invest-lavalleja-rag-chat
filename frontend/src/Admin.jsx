import { useCallback, useEffect, useRef, useState } from "react";
import "./admin.css";

const fmtDate = (value) =>
  new Intl.DateTimeFormat("es-UY", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "America/Montevideo",
  }).format(new Date(value * 1000));
const fmtNumber = (value) => new Intl.NumberFormat("es-UY").format(value);
const fmtSize = (value) =>
  value > 1024 * 1024
    ? `${(value / 1024 / 1024).toFixed(1)} MB`
    : `${Math.ceil(value / 1024)} KB`;
const statusLabel = {
  queued: "En espera",
  running: "Procesando",
  completed: "Completado",
  failed: "Falló",
};
const tabs = [
  ["knowledge", "Base de conocimiento", "book"],
  ["versions", "Versiones", "history"],
  ["users", "Administradores", "users"],
  ["audit", "Actividad", "activity"],
];

function Icon({ name, size = 20 }) {
  const paths = {
    book: (
      <>
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 3H20v19H6.5A2.5 2.5 0 0 1 4 19.5v-14A2.5 2.5 0 0 1 6.5 3Z" />
        <path d="M8 7h8M8 11h6" />
      </>
    ),
    history: (
      <>
        <path d="M3 11a9 9 0 1 1 2.7 7M3 4v7h7" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    users: (
      <>
        <circle cx="9" cy="8" r="3" />
        <path d="M3 21v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 4v2" />
      </>
    ),
    activity: (
      <>
        <path d="M3 12h4l3-8 4 16 3-8h4" />
      </>
    ),
    upload: (
      <>
        <path d="m7 9 5-5 5 5M12 4v12M4 16v4h16v-4" />
      </>
    ),
    arrow: (
      <>
        <path d="M5 12h14m-5-5 5 5-5 5" />
      </>
    ),
    shield: (
      <>
        <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    logout: (
      <>
        <path d="M9 4H4v16h5M9 12h12m-4-4 4 4-4 4" />
      </>
    ),
    file: (
      <>
        <path d="M14 2H5v20h14V7Z" />
        <path d="M14 2v5h5M8 12h8M8 16h6" />
      </>
    ),
    download: (
      <>
        <path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] || paths.book}
    </svg>
  );
}

function ConfirmDialog({ action, close, execute, pending }) {
  const dialog = useRef(null);
  const [text, setText] = useState("");
  useEffect(() => {
    dialog.current.showModal();
  }, []);
  return (
    <dialog
      className="ga-dialog"
      ref={dialog}
      onCancel={(event) => {
        if (pending) event.preventDefault();
        else close();
      }}
      aria-labelledby="confirm-title"
    >
      <h2 id="confirm-title">{action.title}</h2>
      <p>{action.description}</p>
      {action.word && (
        <label className="ga-field">
          Escribí {action.word} para confirmar
          <input
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
      )}
      <div className="ga-actions">
        <button
          className="ga-button ga-secondary"
          disabled={pending}
          onClick={close}
        >
          Cancelar
        </button>
        <button
          className="ga-button ga-danger"
          disabled={pending || (action.word && text !== action.word)}
          onClick={() => execute(action)}
        >
          {pending ? "Procesando…" : action.label}
        </button>
      </div>
    </dialog>
  );
}

export default function Admin() {
  const [session, setSession] = useState(null);
  const [tab, setTab] = useState("knowledge");
  const [data, setData] = useState(null);
  const [versions, setVersions] = useState([]);
  const [users, setUsers] = useState([]);
  const [audit, setAudit] = useState([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);
  const [confirmation, setConfirmation] = useState(null);
  const [replace, setReplace] = useState(null);
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [countdown, setCountdown] = useState(0);
  const fileInput = useRef(null);

  const getSession = useCallback(async () => {
    const response = await fetch("/api/admin/session", { cache: "no-store" });
    if (!response.ok) throw new Error("No se pudo conectar con el panel.");
    const result = await response.json();
    setSession(result);
    setCountdown(result.resend_after || 0);
    return result;
  }, []);

  const api = useCallback(
    async (path, options = {}) => {
      const response = await fetch(`/api/admin${path}`, {
        ...options,
        cache: "no-store",
        headers: {
          "X-CSRF-Token": session?.csrf || "",
          ...(options.body && !(options.body instanceof FormData)
            ? { "Content-Type": "application/json" }
            : {}),
          ...options.headers,
        },
      });
      let result;
      try {
        result = await response.json();
      } catch {
        throw new Error("El servidor devolvió una respuesta inesperada.");
      }
      if (!response.ok) {
        if (response.status === 401 && !["/login", "/verify"].includes(path)) {
          setData(null);
          await getSession();
        }
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : "Revisá los datos ingresados.",
        );
      }
      return result;
    },
    [session?.csrf, getSession],
  );

  const refresh = useCallback(async () => {
    const result = await api("/knowledge");
    setData(result);
    if (tab === "versions") setVersions(await api("/knowledge/revisions"));
    if (tab === "users") setUsers(await api("/users"));
    if (tab === "audit") setAudit(await api("/audit"));
  }, [api, tab]);

  useEffect(() => {
    document.title = "Administración · Gianna";
    getSession().catch((e) => setError(e.message));
  }, [getSession]);
  useEffect(() => {
    if (session?.stage !== "authenticated") return;
    let alive = true;
    const update = async () => {
      try {
        if (alive) await refresh();
      } catch (e) {
        if (alive) setError(e.message);
      }
    };
    update();
    const timer = setInterval(update, data?.busy ? 2500 : 30000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [session?.stage, refresh, data?.busy]);
  useEffect(() => {
    if (countdown <= 0) return;
    const timer = setTimeout(
      () => setCountdown((s) => Math.max(0, s - 1)),
      1000,
    );
    return () => clearTimeout(timer);
  }, [countdown]);

  async function perform(fn) {
    setError("");
    setNotice("");
    setPending(true);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }

  async function login(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await perform(async () => {
      const result = await api("/login", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(form)),
      });
      setSession(result);
      setCountdown(60);
    });
  }

  async function verify(event) {
    event.preventDefault();
    const code = new FormData(event.currentTarget).get("code");
    await perform(async () =>
      setSession(
        await api("/verify", {
          method: "POST",
          body: JSON.stringify({ code }),
        }),
      ),
    );
  }

  const submitJob = async (path, options) => {
    await api(path, options);
    setNotice("Actualización iniciada. Podés seguir el progreso aquí.");
    await refresh();
  };

  async function upload(event) {
    event.preventDefault();
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setError("El límite por archivo es de 10 MB.");
      return;
    }
    const body = new FormData();
    body.set("file", file);
    body.set("title", title);
    if (replace) body.set("replace_id", replace.id);
    await perform(async () => {
      await submitJob("/knowledge/upload", { method: "POST", body });
      setFile(null);
      setTitle("");
      setReplace(null);
      fileInput.current.value = "";
    });
  }

  async function execute(action) {
    await perform(async () => {
      await api(action.path, {
        method: action.method || "POST",
        ...(action.body ? { body: JSON.stringify(action.body) } : {}),
      });
      setConfirmation(null);
      setNotice(action.notice || "Operación iniciada.");
      await refresh();
    });
  }

  const message = (
    <>
      {error && (
        <div className="ga-message ga-error" role="alert">
          {error}
          <button aria-label="Cerrar error" onClick={() => setError("")}>
            ×
          </button>
        </div>
      )}
      {notice && (
        <div className="ga-message" role="status">
          {notice}
          <button aria-label="Cerrar aviso" onClick={() => setNotice("")}>
            ×
          </button>
        </div>
      )}
    </>
  );

  if (session?.stage !== "authenticated")
    return (
      <div className="ga-login">
        <aside className="ga-login-brand">
          <a href="/" className="ga-wordmark">
            gianna<span>INVEST LAVALLEJA</span>
          </a>
          <div>
            <span className="ga-eyebrow">ESPACIO DE ADMINISTRACIÓN</span>
            <h1>
              El conocimiento
              <br />
              detrás de cada
              <br />
              <em>conversación.</em>
            </h1>
            <p>
              Gestioná las fuentes que ayudan a Gianna a orientar a inversores y
              emprendedores de Lavalleja.
            </p>
          </div>
          <div className="ga-login-foot">
            <Icon name="shield" /> Acceso protegido en dos pasos
          </div>
        </aside>
        <main className="ga-login-main">
          <div className="ga-login-card">
            <span className="ga-eyebrow">PANEL DE CONTROL</span>
            <h2>
              {session?.stage === "pending"
                ? "Revisá tu correo"
                : "Bienvenido al panel"}
            </h2>
            <p>
              {session?.stage === "pending"
                ? "Ingresá el código de 6 dígitos que te enviamos. Vence en 10 minutos."
                : "Ingresá con tu cuenta de administrador. Después verificaremos tu acceso por correo."}
            </p>
            {message}
            {!session ? (
              <p aria-live="polite">Conectando…</p>
            ) : session.stage === "pending" ? (
              <form onSubmit={verify}>
                <label className="ga-field">
                  Código de verificación
                  <input
                    className="ga-code"
                    name="code"
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    minLength={6}
                    autoFocus
                    required
                  />
                </label>
                <button
                  className="ga-button ga-primary ga-full"
                  disabled={pending}
                >
                  {pending ? "Verificando…" : "Verificar y entrar"}
                  <Icon name="arrow" />
                </button>
                <button
                  type="button"
                  className="ga-text-button"
                  disabled={pending || countdown > 0}
                  onClick={() =>
                    perform(async () => {
                      await api("/resend", { method: "POST" });
                      setCountdown(60);
                      setNotice("Código reenviado.");
                    })
                  }
                >
                  {countdown > 0
                    ? `Reenviar en ${countdown} s`
                    : "Reenviar código"}
                </button>
                <button
                  type="button"
                  className="ga-text-button"
                  disabled={pending}
                  onClick={() =>
                    perform(async () => {
                      await api("/logout", { method: "POST" });
                      await getSession();
                    })
                  }
                >
                  Volver al inicio de sesión
                </button>
              </form>
            ) : (
              <form onSubmit={login}>
                <label className="ga-field">
                  Correo electrónico
                  <input
                    type="email"
                    name="email"
                    autoComplete="username"
                    placeholder="tu@correo.com"
                    required
                    maxLength={254}
                  />
                </label>
                <label className="ga-field">
                  Contraseña
                  <input
                    type="password"
                    name="password"
                    autoComplete="current-password"
                    required
                    maxLength={256}
                  />
                </label>
                <button
                  className="ga-button ga-primary ga-full"
                  disabled={pending}
                >
                  {pending ? "Enviando código…" : "Continuar"}
                  <Icon name="arrow" />
                </button>
              </form>
            )}
            <p className="ga-login-help">
              El acceso está reservado a administradores registrados.
            </p>
            <a className="ga-back" href="/">
              ← Volver al chat de Gianna
            </a>
          </div>
        </main>
      </div>
    );

  const busy = pending || data?.busy;
  const latest = data?.jobs?.[0];
  return (
    <div className="ga-shell">
      <aside className="ga-sidebar">
        <a href="/admin" className="ga-wordmark">
          gianna<span>INVEST LAVALLEJA</span>
        </a>
        <div className="ga-sidebar-label">ADMINISTRACIÓN</div>
        <nav aria-label="Administración">
          {tabs.map(([id, label, icon]) => (
            <button
              key={id}
              className={tab === id ? "is-active" : ""}
              onClick={() => {
                setTab(id);
                setError("");
                setNotice("");
              }}
            >
              <Icon name={icon} />
              {label}
            </button>
          ))}
        </nav>
        <div className="ga-sidebar-bottom">
          <a href="/" target="_blank" rel="noreferrer">
            Abrir chat <Icon name="arrow" size={16} />
          </a>
          <div className="ga-account">
            <span className="ga-avatar">
              {session.email?.[0]?.toUpperCase()}
            </span>
            <div>
              <strong>Administrador</strong>
              <span title={session.email}>{session.email}</span>
            </div>
          </div>
          <button
            className="ga-logout"
            disabled={pending}
            onClick={() =>
              perform(async () => {
                await api("/logout", { method: "POST" });
                setData(null);
                await getSession();
              })
            }
          >
            <Icon name="logout" size={18} />
            Cerrar sesión
          </button>
        </div>
      </aside>
      <main className="ga-main">
        <header className="ga-topbar">
          <span>
            Invest Lavalleja <span className="ga-divider">/</span>{" "}
            Administración
          </span>
          <span className="ga-protected">
            <Icon name="shield" size={16} />
            Sesión verificada
          </span>
        </header>
        <div className="ga-content">
          <div className="ga-page-heading">
            <div>
              <span className="ga-eyebrow">
                GIANNA / {tab === "knowledge" ? "FUENTES" : "CONTROL"}
              </span>
              <h1>{tabs.find((t) => t[0] === tab)?.[1]}</h1>
              <p>
                {tab === "knowledge"
                  ? "Una fuente confiable para cada respuesta. Cargá y mantené la información del asistente."
                  : tab === "versions"
                    ? "Revisá los cambios y recuperá una base anterior cuando lo necesites."
                    : tab === "users"
                      ? "Administrá quién puede acceder y mantené segura tu cuenta."
                      : "Historial de accesos y cambios en la base de conocimiento."}
              </p>
            </div>
            {tab === "knowledge" && (
              <button
                className="ga-button ga-secondary"
                disabled={busy || !data?.active?.chunks}
                onClick={() =>
                  perform(() =>
                    submitJob("/knowledge/reindex", { method: "POST" }),
                  )
                }
              >
                <Icon name="history" size={17} />
                Reindexar base
              </button>
            )}
          </div>
          {message}
          {!data ? (
            <div className="ga-panel ga-empty">Cargando información…</div>
          ) : (
            <>
              {tab === "knowledge" && (
                <>
                  <div className="ga-stats">
                    <div>
                      <span>Documentos activos</span>
                      <strong>
                        {data.active.documents.length}
                        <small> / {data.documents.length} cargados</small>
                      </strong>
                    </div>
                    <div>
                      <span>Fragmentos de conocimiento</span>
                      <strong>{fmtNumber(data.active.chunks)}</strong>
                    </div>
                    <div>
                      <span>Estado del asistente</span>
                      <strong className="ga-status-text">
                        <i
                          className={
                            data.active.chunks
                              ? "ga-dot"
                              : "ga-dot ga-dot-muted"
                          }
                        />
                        {data.active.chunks
                          ? "Base disponible"
                          : "Sin conocimiento"}
                      </strong>
                    </div>
                  </div>
                  {latest && (
                    <div
                      className={`ga-job ${latest.status === "failed" ? "ga-job-failed" : ""}`}
                      role="status"
                    >
                      <span className={`ga-badge ga-${latest.status}`}>
                        {statusLabel[latest.status]}
                      </span>
                      <div>
                        <strong>
                          {latest.action[0].toUpperCase() +
                            latest.action.slice(1)}
                        </strong>
                        <span>{latest.message}</span>
                      </div>
                      {data.busy && (
                        <span className="ga-spinner" aria-label="Procesando" />
                      )}
                    </div>
                  )}
                  <section className="ga-panel">
                    <div className="ga-section-heading">
                      <div>
                        <h2>
                          {replace
                            ? "Actualizar documento"
                            : "Cargar una fuente"}
                        </h2>
                        <p>
                          {replace
                            ? `Reemplazando “${replace.title}”. La versión actual sigue disponible durante la carga.`
                            : "Word o JSONL de Gianna · Hasta 10 MB por archivo"}
                        </p>
                      </div>
                      {replace && (
                        <button
                          className="ga-text-button"
                          disabled={busy}
                          onClick={() => {
                            setReplace(null);
                            setTitle("");
                          }}
                        >
                          Cancelar reemplazo
                        </button>
                      )}
                    </div>
                    <form className="ga-upload-form" onSubmit={upload}>
                      <label
                        className={`ga-dropzone ${file ? "ga-has-file" : ""}`}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={(e) => {
                          e.preventDefault();
                          if (!busy && e.dataTransfer.files[0])
                            setFile(e.dataTransfer.files[0]);
                        }}
                      >
                        <Icon name="upload" size={26} />
                        <strong>
                          {file
                            ? file.name
                            : "Elegí un archivo o arrastralo aquí"}
                        </strong>
                        <span>
                          {file
                            ? fmtSize(file.size)
                            : "Se conserva el contenido y se preparan los fragmentos automáticamente."}
                        </span>
                        <input
                          type="file"
                          accept=".docx,.jsonl"
                          ref={fileInput}
                          disabled={busy}
                          onChange={(e) => setFile(e.target.files[0] || null)}
                          aria-label="Documento para la base de conocimiento"
                        />
                      </label>
                      <div className="ga-upload-details">
                        <label className="ga-field">
                          Nombre visible
                          <input
                            value={title}
                            maxLength={200}
                            placeholder="Ej. Guía de inversiones 2026"
                            disabled={busy}
                            onChange={(e) => setTitle(e.target.value)}
                          />
                        </label>
                        <p>
                          {replace && !replace.enabled
                            ? "Actualizás una fuente inactiva. Seguirá fuera de la base hasta que la actives."
                            : "El documento se activa al terminar la vectorización. Los anexos internos del Word quedan excluidos."}
                        </p>
                        <button
                          className="ga-button ga-primary"
                          disabled={busy || !file}
                        >
                          <Icon name="upload" size={17} />
                          {pending
                            ? "Cargando…"
                            : replace
                              ? replace.enabled
                                ? "Actualizar y vectorizar"
                                : "Actualizar documento"
                              : "Cargar y vectorizar"}
                        </button>
                      </div>
                    </form>
                  </section>
                  <section className="ga-panel ga-documents">
                    <div className="ga-section-heading">
                      <div>
                        <h2>Documentos</h2>
                        <p>
                          Las fuentes activas forman la base que consulta
                          Gianna.
                        </p>
                      </div>
                      <span className="ga-count">
                        {data.documents.length} fuentes
                      </span>
                    </div>
                    {data.documents.length ? (
                      <div className="ga-table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Fuente</th>
                              <th>Estado</th>
                              <th>Fragmentos</th>
                              <th>Acciones</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.documents.map((doc) => (
                              <tr key={doc.id}>
                                <td>
                                  <div className="ga-document-name">
                                    <span className="ga-file-icon">
                                      <Icon name="file" />
                                    </span>
                                    <div>
                                      <strong>{doc.title}</strong>
                                      <span>
                                        {doc.name} · {fmtSize(doc.size)}
                                      </span>
                                    </div>
                                  </div>
                                </td>
                                <td>
                                  <span
                                    className={`ga-badge ${doc.enabled ? "ga-completed" : "ga-inactive"}`}
                                  >
                                    {doc.enabled ? "Activo" : "Inactivo"}
                                  </span>
                                </td>
                                <td>{fmtNumber(doc.chunks)}</td>
                                <td>
                                  <div className="ga-row-actions">
                                    <a
                                      href={`/api/admin/knowledge/documents/${doc.id}/download`}
                                      className="ga-icon-button"
                                      title="Descargar JSONL"
                                      aria-label={`Descargar ${doc.title}`}
                                    >
                                      <Icon name="download" size={17} />
                                    </a>
                                    <button
                                      disabled={busy}
                                      onClick={() => {
                                        setReplace(doc);
                                        setTitle(doc.title);
                                        document
                                          .querySelector(".ga-upload-form")
                                          ?.scrollIntoView({
                                            behavior: "smooth",
                                            block: "center",
                                          });
                                      }}
                                    >
                                      Actualizar
                                    </button>
                                    <button
                                      disabled={busy}
                                      onClick={() =>
                                        perform(() =>
                                          submitJob(
                                            `/knowledge/documents/${doc.id}/enabled`,
                                            {
                                              method: "POST",
                                              body: JSON.stringify({
                                                enabled: !doc.enabled,
                                              }),
                                            },
                                          ),
                                        )
                                      }
                                    >
                                      {doc.enabled ? "Desactivar" : "Activar"}
                                    </button>
                                    <button
                                      className="ga-delete-link"
                                      disabled={busy}
                                      onClick={() =>
                                        setConfirmation({
                                          title: "Eliminar documento",
                                          description: `“${doc.title}” se quitará de la base y se eliminará su archivo. Las versiones que lo contienen ya no podrán restaurarse.`,
                                          label: "Eliminar",
                                          path: `/knowledge/documents/${doc.id}`,
                                          method: "DELETE",
                                        })
                                      }
                                    >
                                      Eliminar
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="ga-empty">
                        <Icon name="book" size={32} />
                        <h3>Tu base comienza con una fuente</h3>
                        <p>
                          Cargá la guía en Word o el JSONL preparado para
                          producción.
                        </p>
                      </div>
                    )}
                  </section>
                  <div className="ga-danger-zone">
                    <div>
                      <strong>Vaciar la base activa</strong>
                      <p>
                        Gianna dejará de responder consultas. Los archivos y las
                        versiones anteriores se conservan para recuperarlos.
                      </p>
                    </div>
                    <button
                      className="ga-button ga-danger-outline"
                      disabled={busy || !data.active.chunks}
                      onClick={() =>
                        setConfirmation({
                          title: "Vaciar la base de conocimiento",
                          description:
                            "El asistente quedará sin conocimiento hasta que actives documentos o restaures una versión. Se conservarán los archivos y el historial.",
                          word: "VACIAR",
                          label: "Vaciar base",
                          path: "/knowledge/clear",
                          body: { confirm: "VACIAR" },
                        })
                      }
                    >
                      Vaciar base
                    </button>
                  </div>
                </>
              )}
              {tab === "versions" && (
                <section className="ga-panel">
                  <div className="ga-section-heading">
                    <div>
                      <h2>Historial de la base</h2>
                      <p>
                        Cada actualización validada crea una versión. Eliminar
                        una versión borra su índice guardado.
                      </p>
                    </div>
                  </div>
                  <div className="ga-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Versión</th>
                          <th>Contenido</th>
                          <th>Estado</th>
                          <th>Acciones</th>
                        </tr>
                      </thead>
                      <tbody>
                        {versions.map((v) => (
                          <tr key={v.id}>
                            <td>
                              <strong>{v.action}</strong>
                              <span className="ga-table-sub">
                                {fmtDate(v.created)} · {v.id.slice(0, 8)}
                              </span>
                            </td>
                            <td>
                              {v.documents.length} documentos ·{" "}
                              {fmtNumber(v.chunks)} fragmentos
                            </td>
                            <td>
                              <span
                                className={`ga-badge ${v.active ? "ga-completed" : "ga-inactive"}`}
                              >
                                {v.active
                                  ? "Activa"
                                  : v.restorable
                                    ? "Disponible"
                                    : "Fuente eliminada"}
                              </span>
                            </td>
                            <td>
                              <div className="ga-row-actions">
                                <button
                                  disabled={busy || v.active || !v.restorable}
                                  onClick={() =>
                                    setConfirmation({
                                      title: "Restaurar versión",
                                      description: `Se activará la base del ${fmtDate(v.created)} con ${v.documents.length} documentos.`,
                                      label: "Restaurar",
                                      path: `/knowledge/revisions/${v.id}/restore`,
                                    })
                                  }
                                >
                                  Restaurar
                                </button>
                                <button
                                  className="ga-delete-link"
                                  disabled={busy || v.active}
                                  onClick={() =>
                                    setConfirmation({
                                      title: "Eliminar versión guardada",
                                      description:
                                        "Su índice se borrará de forma permanente. Los documentos cargados se conservan.",
                                      label: "Eliminar versión",
                                      path: `/knowledge/revisions/${v.id}`,
                                      method: "DELETE",
                                      notice: "Versión eliminada.",
                                    })
                                  }
                                >
                                  Eliminar
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {!versions.length && (
                    <div className="ga-empty">
                      Las versiones aparecerán después de la primera carga.
                    </div>
                  )}
                </section>
              )}
              {tab === "users" && (
                <>
                  <section className="ga-panel">
                    <div className="ga-section-heading">
                      <div>
                        <h2>Acceso al panel</h2>
                        <p>
                          Todos los administradores verifican su acceso por
                          correo.
                        </p>
                      </div>
                    </div>
                    <div className="ga-table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Correo</th>
                            <th>Estado</th>
                            <th>Acciones</th>
                          </tr>
                        </thead>
                        <tbody>
                          {users.map((user) => (
                            <tr key={user.id}>
                              <td>
                                {user.email}
                                {user.email === session.email && (
                                  <span className="ga-you">Vos</span>
                                )}
                              </td>
                              <td>
                                <span
                                  className={`ga-badge ${user.active ? "ga-completed" : "ga-inactive"}`}
                                >
                                  {user.active ? "Activo" : "Desactivado"}
                                </span>
                              </td>
                              <td>
                                <button
                                  className="ga-text-button"
                                  disabled={
                                    pending || user.email === session.email
                                  }
                                  onClick={() =>
                                    perform(async () => {
                                      await api(`/users/${user.id}/enabled`, {
                                        method: "POST",
                                        body: JSON.stringify({
                                          enabled: !user.active,
                                        }),
                                      });
                                      await refresh();
                                    })
                                  }
                                >
                                  {user.active
                                    ? "Desactivar acceso"
                                    : "Activar acceso"}
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                  <div className="ga-form-grid">
                    <section className="ga-panel">
                      <h2>Agregar administrador</h2>
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          const form = e.currentTarget;
                          const body = Object.fromEntries(new FormData(form));
                          perform(async () => {
                            await api("/users", {
                              method: "POST",
                              body: JSON.stringify(body),
                            });
                            form.reset();
                            setNotice("Administrador creado.");
                            await refresh();
                          });
                        }}
                      >
                        <label className="ga-field">
                          Correo
                          <input
                            type="email"
                            name="email"
                            required
                            maxLength={254}
                          />
                        </label>
                        <label className="ga-field">
                          Contraseña inicial
                          <input
                            type="password"
                            name="password"
                            required
                            minLength={12}
                            maxLength={256}
                            autoComplete="new-password"
                          />
                        </label>
                        <p className="ga-form-help">
                          Usá al menos 12 caracteres. Compartí la contraseña
                          inicial por un canal privado.
                        </p>
                        <button
                          className="ga-button ga-primary"
                          disabled={pending}
                        >
                          Crear administrador
                        </button>
                      </form>
                    </section>
                    <section className="ga-panel">
                      <h2>Cambiar mi contraseña</h2>
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          const body = Object.fromEntries(
                            new FormData(e.currentTarget),
                          );
                          perform(async () => {
                            setSession(
                              await api("/password", {
                                method: "POST",
                                body: JSON.stringify(body),
                              }),
                            );
                            setData(null);
                            setNotice(
                              "Contraseña cambiada. Ingresá nuevamente.",
                            );
                          });
                        }}
                      >
                        <label className="ga-field">
                          Contraseña actual
                          <input
                            type="password"
                            name="current_password"
                            required
                            autoComplete="current-password"
                          />
                        </label>
                        <label className="ga-field">
                          Nueva contraseña
                          <input
                            type="password"
                            name="password"
                            required
                            minLength={12}
                            maxLength={256}
                            autoComplete="new-password"
                          />
                        </label>
                        <p className="ga-form-help">
                          El cambio cierra todas tus sesiones abiertas.
                        </p>
                        <button
                          className="ga-button ga-secondary"
                          disabled={pending}
                        >
                          Actualizar contraseña
                        </button>
                      </form>
                    </section>
                  </div>
                </>
              )}
              {tab === "audit" && (
                <section className="ga-panel">
                  <div className="ga-section-heading">
                    <div>
                      <h2>Últimos movimientos</h2>
                      <p>
                        Los 100 eventos más recientes. No se registran
                        contraseñas ni códigos de acceso.
                      </p>
                    </div>
                  </div>
                  <div className="ga-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Fecha</th>
                          <th>Administrador</th>
                          <th>Acción</th>
                          <th>Referencia</th>
                        </tr>
                      </thead>
                      <tbody>
                        {audit.map((item) => (
                          <tr key={item.id}>
                            <td>{fmtDate(item.at)}</td>
                            <td>{item.actor}</td>
                            <td>{item.action}</td>
                            <td className="ga-audit-detail">
                              {item.detail || "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {!audit.length && (
                    <div className="ga-empty">
                      Todavía no hay actividad registrada.
                    </div>
                  )}
                </section>
              )}
            </>
          )}
          <footer className="ga-footer">
            Gianna · Invest Lavalleja
            <span>Conocimiento cuidado, decisiones mejor informadas.</span>
          </footer>
        </div>
      </main>
      {confirmation && (
        <ConfirmDialog
          action={confirmation}
          close={() => !pending && setConfirmation(null)}
          execute={execute}
          pending={pending}
        />
      )}
    </div>
  );
}
