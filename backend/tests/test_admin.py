import asyncio
import json
import time
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_api import AdminHeaders, admin_router
from admin_auth import AdminAuth
from admin_db import AdminDB
from knowledge_admin import KnowledgeAdmin
from knowledge_format import SCHEMA, read_jsonl

EMAIL = "admin@example.test"
PASSWORD = "Only-for-tests-2026!"


def corpus(text="Información pública de prueba.", doc="fuente"):
    records = [{"type": "manifest", "schema": SCHEMA, "title": "Fuente de prueba", "chunk_count": 1},
               {"type": "chunk", "id": 0, "section": "Z1 / MINAS > O01 · Servicio",
                "text": text, "zone": "Z1", "card": "O01", "doc": doc}]
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in records).encode()


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET_KEY", "test-secret-" * 6)
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    db = AdminDB(tmp_path)
    mail = []
    auth = AdminAuth(db, mailer=lambda email, code: mail.append((email, code)))
    auth.create_user(EMAIL, PASSWORD, "test")
    state = {"inflight": 0}

    async def prepare(path):
        chunks = json.loads((path / "chunks.json").read_text(encoding="utf-8"))
        return {"chunks": chunks}

    knowledge = KnowledgeAdmin(db, prepare, state)
    knowledge.recover()

    async def build(selected, output):
        # No red ni modelos: comprueba las transacciones administrativas por separado.
        await asyncio.sleep(.01)
        chunks = []
        for doc_id in selected:
            _, parts = read_jsonl(knowledge.canonical_path(doc_id))
            for part in parts:
                chunks.append({**part, "id": len(chunks)})
        output.mkdir()
        (output / "chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
    knowledge.build = build

    @asynccontextmanager
    async def lifespan(app):
        yield
        await knowledge.close()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(AdminHeaders)
    app.include_router(admin_router(auth, knowledge, db))
    with TestClient(app) as client:
        yield client, auth, knowledge, db, mail, state


def begin_login(system):
    client, _, _, _, mail, _ = system
    csrf = client.get("/api/admin/session").json()["csrf"]
    response = client.post("/api/admin/login", json={"email": EMAIL, "password": PASSWORD}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200, response.text
    return response.json()["csrf"], mail[-1][1]


def login(system):
    csrf, code = begin_login(system)
    response = system[0].post("/api/admin/verify", json={"code": code}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf"]}


def wait_job(system):
    client = system[0]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        data = client.get("/api/admin/knowledge").json()
        if not data["busy"]:
            return data
        time.sleep(.02)
    pytest.fail("La operación no finalizó")


def upload(system, headers, text="Conocimiento", name="fuente.jsonl", replace=None):
    data = {"title": name}
    if replace:
        data["replace_id"] = replace
    response = system[0].post("/api/admin/knowledge/upload", headers=headers, data=data,
                              files={"file": (name, corpus(text, name.rsplit('.', 1)[0]), "application/x-ndjson")})
    assert response.status_code == 202, response.text
    result = wait_job(system)
    assert result["jobs"][0]["status"] == "completed", result
    return result


def test_two_factors_csrf_and_single_use(system):
    client, _, _, db, mail, _ = system
    assert client.get("/api/admin/knowledge").status_code == 401
    anon = client.get("/api/admin/session")
    assert "HttpOnly" in anon.headers["set-cookie"] and "SameSite=strict" in anon.headers["set-cookie"]
    assert client.post("/api/admin/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 403
    assert client.post("/api/admin/login", json={"email": EMAIL, "password": PASSWORD},
                       headers={"X-CSRF-Token": anon.json()["csrf"], "Origin": "https://evil.test"}).status_code == 403
    csrf, code = begin_login(system)
    old_cookie = client.cookies.get("gianna_admin")
    assert client.get("/api/admin/knowledge").status_code == 401
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE stage='pending'").fetchone()
        assert row["code_hash"] != code
    verified = client.post("/api/admin/verify", json={"code": code}, headers={"X-CSRF-Token": csrf})
    assert verified.status_code == 200
    assert client.cookies.get("gianna_admin") != old_cookie
    assert client.get("/api/admin/knowledge").status_code == 200
    replay = client.post("/api/admin/verify", json={"code": code}, headers={"Cookie": f"gianna_admin={old_cookie}", "X-CSRF-Token": csrf})
    assert replay.status_code == 401
    assert client.post("/api/admin/knowledge/reindex").status_code == 403
    assert len(mail) == 1


def test_otp_attempt_budget_and_expiration(system):
    csrf, code = begin_login(system)
    client, _, _, db, _, _ = system
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert client.post("/api/admin/verify", json={"code": wrong}, headers={"X-CSRF-Token": csrf}).status_code == 400
    assert client.post("/api/admin/verify", json={"code": code}, headers={"X-CSRF-Token": csrf}).status_code == 400
    assert client.post("/api/admin/resend", headers={"X-CSRF-Token": csrf}).status_code == 400
    with db.connect() as conn:
        conn.execute("UPDATE sessions SET attempts=0,code_expires=?", (time.time() - 1,))
    assert client.post("/api/admin/verify", json={"code": code}, headers={"X-CSRF-Token": csrf}).status_code == 400


def test_resend_invalidates_old_code_without_resetting_attempts(system):
    csrf, original = begin_login(system)
    client, _, _, db, mail, _ = system
    assert client.post("/api/admin/resend", headers={"X-CSRF-Token": csrf}).status_code == 429
    with db.connect() as conn:
        conn.execute("UPDATE sessions SET sent=?,attempts=4", (time.time() - 61,))
    assert client.post("/api/admin/resend", headers={"X-CSRF-Token": csrf}).status_code == 200
    with db.connect() as conn:
        assert conn.execute("SELECT attempts FROM sessions WHERE stage='pending'").fetchone()[0] == 4
    if original == mail[-1][1]:
        original = "000000" if original != "000000" else "111111"
    assert client.post("/api/admin/verify", json={"code": original}, headers={"X-CSRF-Token": csrf}).status_code == 400
    assert client.post("/api/admin/verify", json={"code": mail[-1][1]}, headers={"X-CSRF-Token": csrf}).status_code == 400


def test_login_rate_limit(system):
    client = system[0]
    csrf = client.get("/api/admin/session").json()["csrf"]
    for _ in range(5):
        assert client.post("/api/admin/login", json={"email": EMAIL, "password": "wrong"}, headers={"X-CSRF-Token": csrf}).status_code == 401
    assert client.post("/api/admin/login", json={"email": EMAIL, "password": PASSWORD}, headers={"X-CSRF-Token": csrf}).status_code == 429


def test_mail_failure_never_authenticates(system):
    client, auth, _, _, _, _ = system
    def fail(*args):
        raise RuntimeError("SMTP secret should never appear")
    auth.mailer = fail
    csrf = client.get("/api/admin/session").json()["csrf"]
    result = client.post("/api/admin/login", json={"email": EMAIL, "password": PASSWORD}, headers={"X-CSRF-Token": csrf})
    assert result.status_code == 503 and "SMTP secret" not in result.text
    assert client.get("/api/admin/session").json()["stage"] == "anonymous"


def test_multi_document_replace_clear_restore_and_delete(system):
    headers = login(system)
    client, _, manager, db, _, state = system
    first = upload(system, headers, "Primero", "primero.jsonl")
    original_revision = first["active"]["id"]
    first_id = first["documents"][0]["id"]
    second = upload(system, headers, "Segundo", "segundo.jsonl")
    assert second["active"]["chunks"] == 2 and [c["id"] for c in state["chunks"]] == [0, 1]
    assert client.get(f"/api/admin/knowledge/documents/{first_id}/download").status_code == 200
    replaced = upload(system, headers, "Actualizado", "nueva.jsonl", replace=first_id)
    assert replaced["active"]["chunks"] == 2
    assert {c["text"] for c in state["chunks"]} == {"Segundo", "Actualizado"}
    assert client.post(f"/api/admin/knowledge/revisions/{original_revision}/restore", headers=headers).status_code == 409
    revision = replaced["active"]["id"]
    assert client.post("/api/admin/knowledge/clear", json={"confirm": "wrong"}, headers=headers).status_code == 400
    assert client.post("/api/admin/knowledge/clear", json={"confirm": "VACIAR"}, headers=headers).status_code == 202
    empty = wait_job(system)
    assert empty["active"]["chunks"] == 0 and state["chunks"] == []
    # Persistencia: un nuevo gestor sigue viendo la base vacía, no recurre al índice original.
    restarted = KnowledgeAdmin(db, manager.prepare_runtime, state)
    assert restarted.manifest()["chunks"] == 0
    assert client.post(f"/api/admin/knowledge/revisions/{revision}/restore", headers=headers).status_code == 202
    assert wait_job(system)["active"]["chunks"] == 2
    assert client.delete(f"/api/admin/knowledge/revisions/{revision}", headers=headers).status_code == 409
    delete_id = client.get("/api/admin/knowledge").json()["documents"][0]["id"]
    assert client.delete(f"/api/admin/knowledge/documents/{delete_id}", headers=headers).status_code == 202
    assert wait_job(system)["active"]["chunks"] == 1
    assert not (manager.root / "documents" / delete_id).exists()


def test_replacing_inactive_source_preserves_its_state(system):
    headers = login(system)
    client, _, _, _, _, state = system
    first = upload(system, headers, "Fuente a desactivar", "inactiva.jsonl")
    old_id = first["documents"][0]["id"]
    upload(system, headers, "Fuente activa", "activa.jsonl")
    assert client.post(f"/api/admin/knowledge/documents/{old_id}/enabled",
                       json={"enabled": False}, headers=headers).status_code == 202
    assert wait_job(system)["active"]["chunks"] == 1
    replaced = upload(system, headers, "Inactiva actualizada", "actualizada.jsonl", replace=old_id)
    new = next(d for d in replaced["documents"] if d["name"] == "actualizada.jsonl")
    assert not new["enabled"] and replaced["active"]["chunks"] == 1
    assert [c["text"] for c in state["chunks"]] == ["Fuente activa"]
    assert client.get(f"/api/admin/knowledge/documents/{old_id}/download").status_code == 404
    assert client.post(f"/api/admin/knowledge/documents/{new['id']}/enabled",
                       json={"enabled": True}, headers=headers).status_code == 202
    assert wait_job(system)["active"]["chunks"] == 2
    assert {c["text"] for c in state["chunks"]} == {"Fuente activa", "Inactiva actualizada"}


def test_failed_build_keeps_current_base_and_busy_rejects_concurrent_edits(system):
    headers = login(system)
    client, _, manager, _, _, state = system
    initial = upload(system, headers)
    snapshot = initial["active"]["id"]
    async def fail(selected, output):
        await asyncio.sleep(.2)
        raise RuntimeError("Fallo simulado de vectorización")
    manager.build = fail
    response = client.post("/api/admin/knowledge/reindex", headers=headers)
    assert response.status_code == 202
    assert client.post("/api/admin/knowledge/clear", json={"confirm": "VACIAR"}, headers=headers).status_code == 409
    result = wait_job(system)
    assert result["jobs"][0]["status"] == "failed"
    assert result["active"]["id"] == snapshot and state["chunks"][0]["text"] == "Conocimiento"
    assert len(manager.revisions()) == 1


def test_upload_validation_and_private_download(system):
    headers = login(system)
    client = system[0]
    for name, content in [("malware.exe", b"bad"), ("empty.jsonl", b""), ("bad.jsonl", b'{"schema":"unknown"}')]:
        assert client.post("/api/admin/knowledge/upload", headers=headers, files={"file": (name, content)}).status_code == 400
    assert client.post("/api/admin/knowledge/upload", headers={**headers, "Content-Length": str(12 * 1024 * 1024)}, content=b"").status_code == 413
    result = upload(system, headers)
    doc_id = result["documents"][0]["id"]
    assert client.post("/api/admin/logout", headers=headers).status_code == 200
    assert client.get(f"/api/admin/knowledge/documents/{doc_id}/download").status_code == 401


def test_accounts_cannot_disable_last_admin_and_password_change_revokes_sessions(system):
    headers = login(system)
    client = system[0]
    user = client.get("/api/admin/users").json()[0]
    assert client.post(f"/api/admin/users/{user['id']}/enabled", json={"enabled": False}, headers=headers).status_code == 409
    assert client.post("/api/admin/users", json={"email": "second@example.test", "password": "short"}, headers=headers).status_code == 400
    assert client.post("/api/admin/password", json={"current_password": "wrong", "password": "New-strong-password!"}, headers=headers).status_code == 400
    result = client.post("/api/admin/password", json={"current_password": PASSWORD, "password": "New-strong-password!"}, headers=headers)
    assert result.status_code == 200 and result.json()["stage"] == "anonymous"
    assert client.get("/api/admin/knowledge").status_code == 401


def test_superadmin_names_roles_and_last_superadmin(system):
    headers = login(system)
    client, auth, _, db, _, _ = system
    primary = client.get("/api/admin/users").json()[0]
    assert primary["is_superadmin"] == 1 and primary["name"]
    created = client.post("/api/admin/users", json={"email": "editor@example.test",
        "password": PASSWORD, "name": "Editor", "is_superadmin": False}, headers=headers)
    assert created.status_code == 201
    assert client.post(f"/api/admin/users/{primary['id']}/role", json={"is_superadmin": False},
                       headers=headers).status_code == 409
    assert client.post(f"/api/admin/users/{primary['id']}/enabled", json={"enabled": False},
                       headers=headers).status_code == 409
    editor = next(user for user in client.get("/api/admin/users").json() if user["email"] == "editor@example.test")
    from fastapi import Response
    auth.new_session(Response(), "authenticated", editor["id"])
    assert client.post(f"/api/admin/users/{editor['id']}/role", json={"is_superadmin": True},
                       headers=headers).status_code == 200
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (editor["id"],)).fetchone()[0] == 0
    assert client.post("/api/admin/users", json={"email": "bad@example.test", "password": PASSWORD,
        "is_superadmin": "false"}, headers=headers).status_code == 422


def test_regular_admin_can_manage_knowledge_but_not_users_or_audit(system):
    client, auth, _, _, mail, _ = system
    auth.create_user("editor@example.test", PASSWORD, "test", "Editor", False)
    csrf = client.get("/api/admin/session").json()["csrf"]
    pending = client.post("/api/admin/login", json={"email": "editor@example.test", "password": PASSWORD},
                          headers={"X-CSRF-Token": csrf}).json()
    verified = client.post("/api/admin/verify", json={"code": mail[-1][1]},
                           headers={"X-CSRF-Token": pending["csrf"]})
    assert verified.status_code == 200
    assert verified.json()["name"] == "Editor" and verified.json()["is_superadmin"] is False
    headers = {"X-CSRF-Token": verified.json()["csrf"]}
    assert client.get("/api/admin/knowledge").status_code == 200
    assert client.get("/api/admin/knowledge/revisions").status_code == 200
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/audit").status_code == 403
    assert client.post("/api/admin/users", json={"email": "new@example.test", "password": PASSWORD},
                       headers=headers).status_code == 403
    assert client.post("/api/admin/users/unknown/role", json={"is_superadmin": True}, headers=headers).status_code == 403
    assert upload(system, headers)["active"]["chunks"] == 1
    changed = client.post("/api/admin/password", json={"current_password": PASSWORD,
        "password": "Editor-new-password-2026!"}, headers=headers)
    assert changed.status_code == 200 and changed.json()["stage"] == "anonymous"


def test_restart_marks_interrupted_job_failed_and_removes_uncommitted_index(system):
    _, _, manager, db, _, state = system
    with db.connect() as conn:
        conn.execute("INSERT INTO jobs(id,action,status,message,created,actor) VALUES('abandoned','index','running','',?,'test')", (time.time(),))
    abandoned = manager.root / "revisions" / ("a" * 32)
    abandoned.mkdir()
    restarted = KnowledgeAdmin(db, manager.prepare_runtime, state)
    restarted.recover()
    assert not abandoned.exists()
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM jobs WHERE id='abandoned'").fetchone()[0] == "failed"
