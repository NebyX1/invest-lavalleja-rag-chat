import importlib
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
from starlette.requests import Request

from chat_access import ChatAccess

ORIGIN = "http://127.0.0.1:8080"


@pytest.fixture
def access(tmp_path):
    clock = [10000.0]
    return ChatAccess(tmp_path, b"stable-test-secret-with-no-real-credentials", [ORIGIN], lambda: clock[0]), clock


def test_twenty_then_full_ten_minutes_and_restart(access, tmp_path):
    store, clock = access
    for i in range(20):
        result = store.quota("ip1", "browser1", True)
        assert result["remaining"] == 19 - i
        clock[0] += 5
    assert result["retry_after"] == 600
    restarted = ChatAccess(tmp_path, store.secret, [ORIGIN], lambda: clock[0])
    with pytest.raises(HTTPException) as error:
        restarted.quota("ip1", "browser1", True)
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "595"
    clock[0] += 594
    assert restarted.quota("ip1", "browser1")["retry_after"] == 1
    clock[0] += 1
    assert restarted.quota("ip1", "browser1", True)["remaining"] == 19


def test_both_ip_and_browser_limits_cannot_be_reset(access):
    store, clock = access
    for _ in range(20):
        store.quota("ip1", "browser1", True)
    # Borrar datos del navegador / nueva sesión no evade el límite de IP.
    with pytest.raises(HTTPException):
        store.quota("ip1", "new-browser", True)
    # Cambiar de red no evade el límite de la sesión del navegador.
    with pytest.raises(HTTPException):
        store.quota("ip2", "browser1", True)
    assert store.quota("ip2", "browser2", True)["remaining"] == 19
    clock[0] += 600
    assert store.quota("ip1", "browser1", True)["remaining"] == 19


def test_concurrent_requests_only_accept_twenty(access):
    store, _ = access
    def consume(_):
        try:
            store.quota("shared-ip", "shared-browser", True)
            return True
        except HTTPException as error:
            assert error.status_code == 429
            return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(consume, range(50))) == 20
    with store.connect() as db:
        assert db.execute("SELECT used FROM quotas").fetchall() == [(20,), (20,)]


def test_only_hashed_identifiers_and_counters_are_persisted(access):
    store, _ = access
    store.quota("192.0.2.4", "a-browser-identifier", True)
    with store.connect() as db:
        assert [row[1] for row in db.execute("PRAGMA table_info(quotas)")] == ["key", "used", "blocked_until", "updated"]
        assert all(len(row[0]) == 64 for row in db.execute("SELECT key FROM quotas"))
    raw = store.path.read_bytes()
    assert b"192.0.2.4" not in raw and b"a-browser-identifier" not in raw


def request(origin=None, token=None):
    headers = []
    if origin: headers.append((b"origin", origin.encode()))
    if token: headers.append((b"x-chat-session", token.encode()))
    return Request({"type": "http", "headers": headers})


def test_portal_origin_signed_session_and_expiry(access):
    store, clock = access
    browser = str(uuid4())
    token = store.issue(browser, ORIGIN)
    assert store.authorize(request(ORIGIN, token)) == browser
    for origin, value, code in [(None, token, 403), ("https://other.test", token, 403),
                                 (ORIGIN, None, 401), (ORIGIN, token + "x", 401)]:
        with pytest.raises(HTTPException) as error:
            store.authorize(request(origin, value))
        assert error.value.status_code == code
    clock[0] += 30 * 86400
    with pytest.raises(HTTPException):
        store.authorize(request(ORIGIN, token))


@pytest.fixture
def api(tmp_path, monkeypatch):
    import config
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    monkeypatch.setenv("ADMIN_SECRET_KEY", "api-quota-test-secret-" * 3)
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(config, "ADMIN_DATA_DIR", tmp_path)
    main = importlib.import_module("main")
    clock = [10000.0]
    access = ChatAccess(tmp_path / "quota", b"api-test-secret", [ORIGIN], lambda: clock[0])
    class Graph:
        async def astream(self, *args, **kwargs):
            yield "messages", (AIMessageChunk(content="Respuesta privada de prueba"), {"langgraph_node": "asesor"})
    monkeypatch.setattr(main, "chat_access", access)
    monkeypatch.setattr(main, "state", {"graph": Graph(), "titles": {}, "inflight": 0})
    return TestClient(main.app), access, clock


def test_api_quota_headers_invalid_input_and_expiry(api, capsys):
    client, access, clock = api
    session = client.post("/api/chat/session", headers={"Origin": ORIGIN}, json={"browser_id": str(uuid4())})
    assert session.status_code == 200 and session.json()["remaining"] == 20
    headers = {"Origin": ORIGIN, "X-Chat-Session": session.json()["token"]}
    for content in ("", "x" * 2001):
        assert client.post("/api/chat", headers=headers, json={"messages": [{"role": "user", "content": content}]}).status_code == 400
    assert client.post("/api/chat/quota", headers=headers).json()["remaining"] == 20
    body = {"messages": [{"role": "user", "content": "Consulta privada que no se guarda"}]}
    for i in range(20):
        response = client.post("/api/chat", headers=headers, json=body)
        assert response.status_code == 200 and 'event: token' in response.text
        assert response.headers["x-chat-remaining"] == str(19 - i)
        assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-chat-retry-after"] == "600"
    blocked = client.post("/api/chat", headers=headers, json=body)
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "600"
    clock[0] += 600
    assert client.post("/api/chat", headers=headers, json=body).status_code == 200
    output = capsys.readouterr().out
    assert body["messages"][0]["content"] not in output and "Respuesta privada" not in output
    assert b"Consulta privada" not in access.path.read_bytes()


def test_backend_serves_only_api_and_cors_credentials(api):
    client, _, _ = api
    for path in ("/", "/gianna/", "/chat/", "/admin", "/assets/app.js"):
        assert client.get(path).status_code == 404
    assert client.get("/api/admin/knowledge").status_code == 401
    assert client.post("/api/chat/session", json={"browser_id": str(uuid4())}).status_code == 403
    response = client.options("/api/chat", headers={"Origin": ORIGIN,
        "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-chat-session"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    denied = client.options("/api/chat", headers={"Origin": "https://other.test", "Access-Control-Request-Method": "POST"})
    assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers
