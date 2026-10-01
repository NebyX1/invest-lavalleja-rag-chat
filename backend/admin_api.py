"""API del panel. Todas las operaciones de conocimiento requieren 2FA + CSRF."""
import re
import time
import uuid
import zipfile

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, StrictBool
from docx.opc.exceptions import PackageNotFoundError
from lxml.etree import XMLSyntaxError

from admin_auth import password_hash, valid_password

MAX_UPLOAD = 10 * 1024 * 1024


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class Code(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class CreateUser(Login):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_superadmin: StrictBool = False


class UserRole(BaseModel):
    is_superadmin: StrictBool


class Enabled(BaseModel):
    enabled: bool


class Password(BaseModel):
    current_password: str = Field(max_length=256)
    password: str = Field(min_length=12, max_length=256)


class Confirmation(BaseModel):
    confirm: str


class AdminHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (scope["path"].startswith("/api/admin") or scope["path"].startswith("/admin")):
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        cap = MAX_UPLOAD + 1024 * 1024 if scope["path"].endswith("/upload") else 64 * 1024
        try:
            size = int(headers.get(b"content-length", b"0"))
        except ValueError:
            size = cap + 1
        if size > cap:
            return await JSONResponse({"detail": "El archivo supera el límite de 10 MB."}, 413)(scope, receive, send)
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > cap:
                raise HTTPException(413, "El archivo supera el límite de 10 MB.")
            return message

        async def secured_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"), (b"referrer-policy", b"no-referrer")]
            await send(message)
        await self.app(scope, limited_receive, secured_send)


def admin_router(auth, knowledge, db):
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    @router.get("/session")
    def session(request: Request, response: Response):
        try:
            row = auth.session(request)
            return {"stage": row["stage"], "csrf": row["csrf"], "email": row["email"],
                    "name": row["name"], "is_superadmin": bool(row["is_superadmin"]),
                    "resend_after": max(0, int(60 - (time.time() - row["sent"])))}
        except HTTPException:
            return auth.new_session(response)

    @router.post("/login")
    def login(body: Login, request: Request, response: Response):
        return auth.login(request, response, body.email, body.password)

    @router.post("/verify")
    def verify(body: Code, request: Request, response: Response):
        return auth.verify(request, response, body.code)

    @router.post("/resend")
    def resend(request: Request):
        return auth.resend(request)

    @router.post("/logout")
    def logout(request: Request, response: Response):
        return auth.logout(request, response)

    @router.get("/knowledge")
    def status(request: Request):
        auth.session(request, True)
        return knowledge.status()

    @router.post("/knowledge/upload", status_code=202)
    async def upload(request: Request):
        actor = auth.protect(request)["email"]
        if knowledge.busy():
            raise HTTPException(409, "Ya hay una operación en curso.")
        source = None
        try:
            async with request.form(max_files=1, max_fields=3, max_part_size=1024) as form:
                file = form.get("file")
                if not file or not hasattr(file, "filename"):
                    raise HTTPException(400, "Seleccioná un archivo.")
                name = re.sub(r"[^\w .-]", "_", (file.filename or "").replace("\\", "/").split("/")[-1])
                if len(name) > 180 or not name.lower().endswith((".docx", ".jsonl")):
                    raise HTTPException(400, "Usá un .docx o un .jsonl de Gianna con un nombre de hasta 180 caracteres.")
                title = form.get("title", "")
                replace_id = form.get("replace_id") or None
                if not isinstance(title, str) or len(title) > 200 or (replace_id and not isinstance(replace_id, str)):
                    raise HTTPException(400, "Datos de documento inválidos.")
                source = knowledge.root / "uploads" / (uuid.uuid4().hex + (".docx" if name.lower().endswith(".docx") else ".jsonl"))
                total = 0
                with source.open("wb") as f:
                    while block := await file.read(64 * 1024):
                        total += len(block)
                        if total > MAX_UPLOAD:
                            raise HTTPException(413, "El archivo supera el límite de 10 MB.")
                        f.write(block)
                if not total:
                    raise HTTPException(400, "El archivo está vacío.")
                return await knowledge.upload(source, name, title.strip(), actor, replace_id)
        except (ValueError, UnicodeError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc)[:250]) from None
        except (PackageNotFoundError, XMLSyntaxError, KeyError):
            raise HTTPException(400, "El Word está dañado o no tiene una estructura válida.") from None
        finally:
            if source:
                source.unlink(missing_ok=True)

    @router.get("/knowledge/documents/{doc_id}/download")
    def download(doc_id: str, request: Request):
        auth.session(request, True)
        doc = knowledge.document(doc_id)
        return FileResponse(knowledge.canonical_path(doc_id), media_type="application/x-ndjson",
                            filename=doc["name"].rsplit(".", 1)[0] + ".jsonl")

    @router.post("/knowledge/documents/{doc_id}/enabled", status_code=202)
    async def enabled(doc_id: str, body: Enabled, request: Request):
        return knowledge.set_enabled(doc_id, body.enabled, auth.protect(request)["email"])

    @router.delete("/knowledge/documents/{doc_id}", status_code=202)
    async def delete(doc_id: str, request: Request):
        return knowledge.delete(doc_id, auth.protect(request)["email"])

    @router.post("/knowledge/reindex", status_code=202)
    async def reindex(request: Request):
        return knowledge.schedule("reindexar", [d["id"] for d in knowledge.manifest()["documents"]], auth.protect(request)["email"])

    @router.post("/knowledge/clear", status_code=202)
    async def clear(body: Confirmation, request: Request):
        actor = auth.protect(request)["email"]
        if body.confirm != "VACIAR":
            raise HTTPException(400, "Escribí VACIAR para confirmar.")
        return knowledge.schedule("vaciar base", [], actor)

    @router.get("/knowledge/revisions")
    def revisions(request: Request):
        auth.session(request, True)
        return knowledge.revisions()

    @router.post("/knowledge/revisions/{revision}/restore", status_code=202)
    async def restore(revision: str, request: Request):
        return knowledge.restore(revision, auth.protect(request)["email"])

    @router.delete("/knowledge/revisions/{revision}")
    async def prune(revision: str, request: Request):
        knowledge.prune(revision, auth.protect(request)["email"])
        return {"ok": True}

    @router.get("/audit")
    def audit(request: Request):
        auth.session(request, True, superadmin=True)
        with db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")]

    @router.get("/users")
    def users(request: Request):
        auth.session(request, True, superadmin=True)
        with db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT id,email,name,is_superadmin,active,created FROM users ORDER BY created")]

    @router.post("/users", status_code=201)
    def create_user(body: CreateUser, request: Request):
        actor = auth.protect(request, superadmin=True)["email"]
        try:
            auth.create_user(body.email, body.password, actor, body.name, body.is_superadmin)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"ok": True}

    @router.post("/users/{user_id}/enabled")
    def enable_user(user_id: str, body: Enabled, request: Request):
        actor = auth.protect(request, superadmin=True)["email"]
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise HTTPException(404, "Administrador inexistente.")
            if not body.enabled and user["active"] and user["is_superadmin"] and conn.execute("SELECT COUNT(*) FROM users WHERE active=1 AND is_superadmin=1").fetchone()[0] <= 1:
                raise HTTPException(409, "Debe quedar al menos un superadministrador activo.")
            conn.execute("UPDATE users SET active=? WHERE id=?", (int(body.enabled), user_id))
            if not body.enabled:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        db.audit(actor, "admin.enable" if body.enabled else "admin.disable", user["email"])
        return {"ok": True}

    @router.post("/users/{user_id}/role")
    def change_role(user_id: str, body: UserRole, request: Request):
        actor = auth.protect(request, superadmin=True)
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise HTTPException(404, "Administrador inexistente.")
            if not body.is_superadmin and user["is_superadmin"] and user["active"] and conn.execute("SELECT COUNT(*) FROM users WHERE active=1 AND is_superadmin=1").fetchone()[0] <= 1:
                raise HTTPException(409, "Debe quedar al menos un superadministrador activo.")
            conn.execute("UPDATE users SET is_superadmin=? WHERE id=?", (int(body.is_superadmin), user_id))
            if bool(user["is_superadmin"]) != body.is_superadmin:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        db.audit(actor["email"], "admin.role_changed", user["email"])
        return {"ok": True}

    @router.post("/password")
    def change_password(body: Password, request: Request, response: Response):
        actor = auth.protect(request)
        auth.limit("password-change:" + actor["user_id"], 5, 60)
        with db.connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE id=?", (actor["user_id"],)).fetchone()
            if not valid_password(user["password_hash"], body.current_password):
                raise HTTPException(400, "La contraseña actual es incorrecta.")
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash(body.password), user["id"]))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        db.audit(actor["email"], "admin.password_changed")
        return auth.new_session(response)

    return router
