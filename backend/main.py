import json
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from pydantic import BaseModel, Field

from advisor import find_focus
from config import FRONTEND_DIST, INDEX_DIR, OLLAMA_API_KEY, OLLAMA_MODEL
from graph import build_graph
from rag import Retriever
from tools import TOOL_LABELS

MAX_MSG_CHARS = 2000
MAX_HISTORY = 8
RATE_LIMIT = 20  # mensajes por minuto por IP
_hits: dict[str, deque] = defaultdict(deque)

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not OLLAMA_API_KEY or not OLLAMA_MODEL:
        raise RuntimeError("Faltan OLLAMA_API_KEY u OLLAMA_MODEL en .env")
    retriever = Retriever()
    overview = (INDEX_DIR / "overview.txt").read_text(encoding="utf-8")
    state["retriever"] = retriever
    state["titles"] = dict(re.findall(r"^- (O\d\d) ([^|]+?) \|", overview, re.M))
    state["http"] = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15))
    state["graph"] = build_graph(retriever, overview, state["http"])
    yield
    await state["http"].aclose()


app = FastAPI(title="Gianna - Invest Lavalleja", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
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
        case _:
            return f"Profundizando en la guía: {str(a.get('consulta', ''))[:70]}…"


def follow_ups(answer: str, p: dict) -> list[dict]:
    """Botones para seguir profundizando en las fichas que mencionó la respuesta."""
    if not answer:
        return []
    deep = p.get("intent") == "profundizar"
    codes = [c for c in find_focus(answer)[0] if not deep or c not in p.get("codes", [])]
    chips = [
        {"label": f"Profundizar en {c} · {state['titles'].get(c, '')}".strip(" ·"),
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
    ip = request.client.host if request.client else "?"
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(429, "Demasiadas consultas, esperá un momento.")
    q.append(now)

    msgs = req.messages[-MAX_HISTORY:]
    if msgs[-1].role != "user" or not msgs[-1].content.strip():
        raise HTTPException(400, "El último mensaje debe ser del usuario.")
    if len(msgs[-1].content) > MAX_MSG_CHARS:
        raise HTTPException(400, f"Máximo {MAX_MSG_CHARS} caracteres por mensaje.")

    lc_msgs = [HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in msgs]

    async def gen():
        yield sse("status", "Analizando tu consulta…")
        answer: list[str] = []
        used: list[str] = []
        p: dict = {}
        try:
            async for mode, payload in state["graph"].astream(
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
                        print("tools:", [(c["name"], c["args"]) for c in calls])
        except Exception as e:  # noqa: BLE001
            print("Agent error:", repr(e))
            yield sse("error", "No pude conectarme con el modelo. Probá de nuevo en unos segundos.")
            yield sse("done", "")
            return
        if used:
            yield sse("tools", list(dict.fromkeys(used)))
        chips = follow_ups("".join(answer), p)
        if chips:
            yield sse("suggest", chips)
        yield sse("done", "")

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/health")
def health():
    return {"ok": True, "model": OLLAMA_MODEL, "chunks": len(state["retriever"].chunks)}


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = (FRONTEND_DIST / path).resolve()
        if path and f.is_file() and FRONTEND_DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
