import importlib
import json

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk


def test_sse_contract_and_version_snapshot_survive_activation(tmp_path, monkeypatch):
    import config
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    monkeypatch.setenv("ADMIN_SECRET_KEY", "chat-contract-test-secret-" * 3)
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(config, "ADMIN_DATA_DIR", tmp_path)
    main = importlib.import_module("main")
    state = {"titles": {"O12": "Título original"}, "inflight": 0}

    class Graph:
        async def astream(self, *args, **kwargs):
            yield "updates", {"entender": {"plan": {"intent": "explorar"}, "sources": ["Fuente original"]}}
            yield "messages", (AIMessageChunk(content="Texto provisional"), {"langgraph_node": "asesor"})
            yield "updates", {"asesor": {"messages": [AIMessage(content="", tool_calls=[{"name": "ver_ficha", "args": {"codigo": "O12"}, "id": "call-1"}])]}}
            # Simula la activación concurrente de otro índice mientras este stream sigue abierto.
            state.update(graph=None, titles={"O12": "Título nuevo"})
            yield "messages", (AIMessageChunk(content="O12: respuesta final"), {"langgraph_node": "asesor"})

    state["graph"] = Graph()
    monkeypatch.setattr(main, "state", state)
    from chat_access import ChatAccess
    origin = "http://127.0.0.1:8080"
    access = ChatAccess(tmp_path, b"contract-test-secret", [origin])
    monkeypatch.setattr(main, "chat_access", access)
    client = TestClient(main.app)
    headers = {"Origin": origin, "X-Chat-Session": access.issue("00000000-0000-4000-8000-000000000001", origin)}
    response = client.post("/api/chat", headers=headers, json={"messages": [{"role": "user", "content": "Consulta de prueba"}]})
    assert response.status_code == 200
    assert response.headers["x-accel-buffering"] == "no"
    events = [(block.splitlines()[0][7:], json.loads(block.splitlines()[1][6:])) for block in response.text.strip().split("\n\n")]
    assert [name for name, _ in events] == ["status", "sources", "status", "token", "reset", "status", "token", "tools", "suggest", "done"]
    assert "Título original" in next(value for name, value in events if name == "suggest")[0]["label"]
    assert state["inflight"] == 0
    # Con base vacía no se consulta al modelo; la API administrativa puede seguir disponible.
    assert client.post("/api/chat", headers=headers, json={"messages": [{"role": "user", "content": "Hola"}]}).status_code == 503
    assert client.get("/api/health").json()["knowledge_ready"] is False
