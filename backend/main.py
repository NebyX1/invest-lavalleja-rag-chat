import asyncio
import json
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from pydantic import BaseModel, Field

from advisor import find_focus
from config import ADMIN_DATA_DIR, CORS_ORIGINS, OLLAMA_API_KEY, OLLAMA_MODEL
from chat_access import ChatAccess, BrowserSession
from admin_api import AdminHeaders, admin_router
from admin_auth import AdminAuth
from admin_db import AdminDB
from admin_runtime import RuntimeLock
from knowledge_admin import KnowledgeAdmin
from graph import build_graph
from rag import Retriever
from tools import TOOL_LABELS

MAX_MSG_CHARS = 2000
MAX_HISTORY = 8

state: dict = {}


class ChatStream(StreamingResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            state["inflight"] -= 1


async def prepare_runtime(index_dir):
    chunks = json.loads((index_dir / "chunks.json").read_text(encoding="utf-8"))
    if not chunks:
        return {"retriever": None, "graph": None, "titles": {}}
    resources = state.get("resources", {})
    retriever = await asyncio.to_thread(Retriever, index_dir, resources.get("model"), resources.get("reranker"))
    await asyncio.to_thread(retriever.search, "verificación de la base", 1)
    await asyncio.to_thread(retriever.reranker.score, "warmup", ["warmup"])
    overview = (index_dir / "overview.txt").read_text(encoding="utf-8")
    return {"retriever": retriever,
            "titles": dict(re.findall(r"^- (O\d\d) ([^|]+?) \|", overview, re.M)),
            "graph": build_graph(retriever, overview, state["http"]),
            "resources": {"model": retriever.model, "reranker": retriever.reranker}}


admin_db = AdminDB(ADMIN_DATA_DIR)
admin_auth = AdminAuth(admin_db)
chat_access = ChatAccess(ADMIN_DATA_DIR, admin_auth.secret, CORS_ORIGINS)
knowledge = KnowledgeAdmin(admin_db, prepare_runtime, state)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not OLLAMA_API_KEY or not OLLAMA_MODEL:
        raise RuntimeError("Faltan OLLAMA_API_KEY u OLLAMA_MODEL en .env")
    lock = RuntimeLock(ADMIN_DATA_DIR / "runtime.lock")
    try:
        knowledge.recover()
        await asyncio.to_thread(knowledge.bootstrap_legacy)
        state["http"] = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15))
        state["inflight"] = 0
        state.update({"retriever": None, "graph": None, "titles": {}})
        if index_dir := knowledge.active_path():
            state.update(await prepare_runtime(index_dir))
        state["revision"] = knowledge.active_id()
        yield
    finally:
        await knowledge.close()
        if state.get("http"):
            await state["http"].aclose()
        lock.close()


app = FastAPI(title="Gianna - Invest Lavalleja", lifespan=lifespan)
app.add_middleware(AdminHeaders)
app.include_router(admin_router(admin_auth, knowledge, admin_db))
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["POST", "GET", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Chat-Session"],
    expose_headers=["Retry-After", "X-Chat-Remaining", "X-Chat-Retry-After"],
)


class Message(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=6000)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=50)


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def tool_status(tc: dict) -> str:
    a = tc.get("args", {})
    match tc["name"]:
        case "ver_ficha":
            return f"Revisando la ficha {a.get('codigo', '')}…"
        case "ver_zona":
            return f"Revisando la zona {a.get('zona', '')}…"
        case "comparar_oportunidades":
            return "Comparando oportunidades…"
        case "filtrar_oportunidades":
            return "Filtrando oportunidades…"
        case "contactos_institucionales":
            return "Buscando contactos institucionales…"
        case "simulador_equilibrio":
            return "Calculando escenarios…"
        case "buscar_guia_reranker":
            return f"Refinando la búsqueda con el reranker: {str(a.get('consulta', ''))[:60]}…"
        case _:
            return f"Profundizando en la guía: {str(a.get('consulta', ''))[:70]}…"


def follow_ups(answer: str, p: dict, titles=None) -> list[dict]:
    """Botones para seguir profundizando en las fichas que mencionó la respuesta."""
    if not answer:
        return []
    deep = p.get("intent") == "profundizar"
    codes = [c for c in find_focus(answer)[0] if not deep or c not in p.get("codes", [])]
    chips = [
        {"label": f"Profundizar en {c} · {(state['titles'] if titles is None else titles).get(c, '')}".strip(" ·"),
         "text": f"Profundizame la oportunidad {c}: cómo entrar, cómo validarla y próximos pasos"}
        for c in codes[:3]
    ]
    if deep:
        chips += [
            {"label": "Incentivos y permisos", "text": "¿Qué incentivos fiscales y permisos aplican a esto?"},
            {"label": "Armar plan de validación", "text": "Armame un plan de validación paso a paso antes de invertir"},
        ]
    return chips[:4]


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    browser = chat_access.authorize(request)
    graph, titles = state.get("graph"), state.get("titles", {})
    if graph is None:
        raise HTTPException(503, "La base de conocimiento está vacía. El administrador debe activar un documento.")
    msgs = req.messages[-MAX_HISTORY:]
    if msgs[-1].role != "user" or not msgs[-1].content.strip():
        raise HTTPException(400, "El último mensaje debe ser del usuario.")
    if len(msgs[-1].content) > MAX_MSG_CHARS:
        raise HTTPException(400, f"Máximo {MAX_MSG_CHARS} caracteres por mensaje.")

    quota = await asyncio.to_thread(chat_access.quota, request.client.host if request.client else "?", browser, True)

    lc_msgs = [HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in msgs]

    async def stream():
        yield sse("status", "Analizando tu consulta…")
        answer: list[str] = []
        used: list[str] = []
        p: dict = {}
        try:
            async for mode, payload in graph.astream(
                {"messages": lc_msgs}, config={"recursion_limit": 25}, stream_mode=["messages", "updates"]
            ):
                if mode == "messages":
                    chunk, meta = payload
                    if meta.get("langgraph_node") == "asesor" and isinstance(chunk, AIMessageChunk) and chunk.content:
                        answer.append(str(chunk.content))
                        yield sse("token", str(chunk.content))
                    continue
                for node, upd in payload.items():
                    if node == "entender":
                        p = upd["plan"]
                        yield sse("sources", upd["sources"])
                        yield sse("status", "Preparando la respuesta…")
                    elif node == "asesor" and upd["messages"][-1].tool_calls:
                        calls = upd["messages"][-1].tool_calls
                        answer.clear()
                        yield sse("reset", "")  # descarta el texto previo a la llamada de herramientas
                        yield sse("status", tool_status(calls[0]))
                        used += [TOOL_LABELS.get(c["name"], c["name"]) for c in calls]
        except Exception as e:  # noqa: BLE001
            print("Agent error:", type(e).__name__)  # Nunca registrar consultas ni respuestas.
            yield sse("error", "No pude conectarme con el modelo. Probá de nuevo en unos segundos.")
            yield sse("done", "")
            return
        if used:
            yield sse("tools", list(dict.fromkeys(used)))
        chips = follow_ups("".join(answer), p, titles)
        if chips:
            yield sse("suggest", chips)
        yield sse("done", "")

    state["inflight"] += 1
    return ChatStream(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no",
        "X-Chat-Remaining": str(quota["remaining"]), "X-Chat-Retry-After": str(quota["retry_after"])})


@app.post("/api/chat/session")
def chat_session(body: BrowserSession, request: Request):
    chat_access.origin(request)
    ip = request.client.host if request.client else "?"
    return {"token": chat_access.issue(body.browser_id, request.headers["origin"]),
            **chat_access.quota(ip, str(body.browser_id))}


@app.post("/api/chat/quota")
def chat_quota(request: Request):
    browser = chat_access.authorize(request)
    return chat_access.quota(request.client.host if request.client else "?", browser)


@app.get("/api/health")
def health():
    retriever = state.get("retriever")
    return {"ok": True, "model": OLLAMA_MODEL, "chunks": len(retriever.chunks) if retriever else 0,
            "knowledge_ready": retriever is not None}
