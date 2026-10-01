"""Agente de inversiones (LangGraph): entender → asesor ⇄ herramientas."""
import asyncio
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from advisor import plan
from config import OLLAMA_API_KEY, OLLAMA_HOST, OLLAMA_MODEL, TOP_K
from prompt import MODES, SYSTEM_PROMPT, TOOLS_GUIDE
from rag import Retriever
from tools import build_tools

MAX_TOOL_ROUNDS = 4
LOW_CONFIDENCE = 0.45  # similitud coseno máxima por debajo de la cual el contexto inicial se considera débil
LOW_CONFIDENCE_NOTE = (
    "\n\nCONFIANZA DEL CONTEXTO: baja. Los fragmentos recuperados parecen poco relacionados con la consulta; "
    "considerá buscar_guia_reranker con una consulta reformulada antes de responder."
)


class Turn:
    """Adaptador mínimo para el planificador (role/content)."""

    def __init__(self, role: str, content: str):
        self.role, self.content = role, content


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    profile: str
    mode: str
    context: str
    sources: list[str]
    plan: dict
    rounds: int
    low_confidence: bool


def build_context(hits) -> str:
    return "\n\n".join(f"<fragmento sección=\"{h['section']}\">\n{h['text']}\n</fragmento>" for h in hits)


def build_graph(retriever: Retriever, overview: str, http_client):
    tools = build_tools(retriever, overview)
    llm = ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_HOST,
        client_kwargs={"headers": {"Authorization": f"Bearer {OLLAMA_API_KEY}"}},
        reasoning=False,
        temperature=0.35,
        num_predict=1600,
    )
    llm_tools = llm.bind_tools(tools)

    async def entender(state: AgentState):
        turns = [Turn("user" if m.type == "human" else "assistant", str(m.content)) for m in state["messages"]]
        p = await plan(http_client, OLLAMA_HOST, OLLAMA_API_KEY, OLLAMA_MODEL, turns)
        k = TOP_K + 4 if p["intent"] == "profundizar" else TOP_K
        hits = await asyncio.to_thread(retriever.gather, p["queries"], p["codes"], p["zones"], k)
        return {
            "profile": p["profile"],
            "mode": MODES[p["intent"]],
            "context": build_context(hits),
            "sources": list(dict.fromkeys(h["section"].split(" > ", 1)[-1] for h in hits if h["score"] >= 0.4))[:3],
            "plan": p,
            "rounds": 0,
            "low_confidence": p["intent"] not in ("saludo", "fuera_de_tema")
            and max((h["score"] for h in hits), default=0.0) < LOW_CONFIDENCE,
        }

    async def asesor(state: AgentState):
        system = (
            f"{SYSTEM_PROMPT}\n\n{TOOLS_GUIDE}\n\nCATÁLOGO:\n{overview}"
            f"\n\nPERFIL DEL INVERSOR (deducido del chat): {state['profile'] or 'todavía sin datos'}"
            f"\n\nMODO DE ESTA RESPUESTA: {state['mode']}"
            f"\n\nCONTEXTO INICIAL RECUPERADO:\n{state['context']}"
            f"{state['low_confidence'] and LOW_CONFIDENCE_NOTE or ''}"
        )
        model = llm_tools if state["rounds"] < MAX_TOOL_ROUNDS else llm
        msg: AIMessage = await model.ainvoke([SystemMessage(system), *state["messages"]])
        return {"messages": [msg], "rounds": state["rounds"] + 1}

    def route(state: AgentState):
        last = state["messages"][-1]
        return "herramientas" if getattr(last, "tool_calls", None) else END

    g = StateGraph(AgentState)
    g.add_node("entender", entender)
    g.add_node("asesor", asesor)
    g.add_node("herramientas", ToolNode(tools))
    g.add_edge(START, "entender")
    g.add_edge("entender", "asesor")
    g.add_conditional_edges("asesor", route, {"herramientas": "herramientas", END: END})
    g.add_edge("herramientas", "asesor")
    return g.compile()
