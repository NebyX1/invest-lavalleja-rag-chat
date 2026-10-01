"""Contraseña + correo obligatorio. Cookies opacas y sesiones revocables en SQLite."""
import hashlib
import hmac
import os
import re
import secrets
import smtplib
import ssl
import time
import uuid
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException, Request, Response

COOKIE = "gianna_admin"
ph = PasswordHasher()
DUMMY_HASH = ph.hash(secrets.token_urlsafe(32))


def password_hash(password):
    if not 12 <= len(password) <= 256:
        raise ValueError("La contraseña debe tener entre 12 y 256 caracteres.")
    return ph.hash(password)


def valid_password(encoded, password):
    try:
        return ph.verify(encoded, password)
    except VerificationError:
        return False


def normalize_email(value):
    email = value.strip().lower()
    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", email) or len(email) > 254:
        raise ValueError("Ingresá un correo válido.")
    return email


def normalize_name(value):
    name = value.strip()
    if not 1 <= len(name) <= 80 or not name.isprintable():
        raise ValueError("El nombre debe tener entre 1 y 80 caracteres visibles.")
    return name


def send_code(email, code):
    host = os.getenv("MAIL_SERVER", "")
    use_ssl = os.getenv("MAIL_USE_SSL", "false").lower() in ("true", "1", "t")
    use_tls = os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "t")
    if not host or (use_ssl and use_tls):
        raise ValueError("Configuración SMTP incompleta o incompatible.")
    if not (use_ssl or use_tls) and os.getenv("MAIL_ALLOW_INSECURE", "false").lower() != "true":
        raise ValueError("SMTP requiere TLS o SSL.")
    sender = os.getenv("MAIL_DEFAULT_SENDER") or os.getenv("MAIL_USERNAME", "")
    if not parseaddr(sender)[1]:
        raise ValueError("Falta MAIL_DEFAULT_SENDER.")
    message = EmailMessage()
    message["Subject"] = "Invest Lavalleja · Código de acceso administrativo"
    message["From"] = sender
    message["To"] = email
    message.set_content(f"Tu código de acceso es: {code}\n\nVence en 10 minutos y puede usarse una sola vez.\nSi no solicitaste el acceso, ignorá este correo.")
    context = ssl.create_default_context()
    port = int(os.getenv("MAIL_PORT", "465" if use_ssl else "587"))
    client = smtplib.SMTP_SSL(host, port, timeout=20, context=context) if use_ssl else smtplib.SMTP(host, port, timeout=20)
    with client as smtp:
        if use_tls:
            smtp.starttls(context=context)
        username = os.getenv("MAIL_USERNAME", "")
        if username:
            smtp.login(username, os.getenv("MAIL_PASSWORD", ""))
        smtp.send_message(message)


class AdminAuth:
    def __init__(self, db, mailer=send_code, bootstrap=True):
        self.db, self.mailer = db, mailer
        self.secure = os.getenv("ADMIN_COOKIE_SECURE", "false").lower() == "true"
        self.samesite = os.getenv("ADMIN_COOKIE_SAMESITE", "strict").lower()
        if self.samesite not in ("strict", "lax", "none") or (self.samesite == "none" and not self.secure):
            raise ValueError("ADMIN_COOKIE_SAMESITE inválido; none requiere HTTPS y ADMIN_COOKIE_SECURE=true.")
        self.ttl = int(os.getenv("ADMIN_SESSION_HOURS", "8")) * 3600
        if not 3600 <= self.ttl <= 86400:
            raise ValueError("ADMIN_SESSION_HOURS debe estar entre 1 y 24.")
        secret = os.getenv("ADMIN_SECRET_KEY", "")
        if secret and len(secret) < 32:
            raise ValueError("ADMIN_SECRET_KEY necesita al menos 32 caracteres.")
        if not secret:
            if self.secure:
                raise ValueError("Configurá ADMIN_SECRET_KEY para producción.")
            path = db.root / "local-secret"
            if not path.exists():
                path.write_text(secrets.token_urlsafe(48), encoding="ascii")
            secret = path.read_text(encoding="ascii").strip()
        self.secret = secret.encode()
        self.origins = {s.rstrip("/") for s in os.getenv("ADMIN_ALLOWED_ORIGINS", "").split(",") if s}
        self.origins.update(s.strip().rstrip("/") for s in os.getenv("CORS_ORIGINS", "").split(",") if s.strip())
        if not self.secure:
            self.origins.update(("http://localhost:5173", "http://127.0.0.1:5173"))
        email, password = os.getenv("ADMIN_EMAIL"), os.getenv("ADMIN_PASSWORD")
        if bootstrap and email and password:
            with db.connect() as conn:
                exists = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            if not exists:
                self.create_user(email, password, "bootstrap", os.getenv("ADMIN_NAME") or "Administrador", True)

    def create_user(self, email, password, actor, name=None, is_superadmin=True):
        email, encoded = normalize_email(email), password_hash(password)
        name = normalize_name(name if name is not None else email)
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                raise ValueError("Ya existe un administrador con ese correo.")
            if not is_superadmin and not conn.execute("SELECT 1 FROM users WHERE active=1 AND is_superadmin=1 LIMIT 1").fetchone():
                raise ValueError("El primer administrador debe ser superadministrador.")
            conn.execute("INSERT INTO users(id,email,password_hash,created,name,is_superadmin) VALUES(?,?,?,?,?,?)",
                         (uuid.uuid4().hex, email, encoded, time.time(), name, int(is_superadmin)))
        self.db.audit(actor, "admin.create", email)

    def digest(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def new_session(self, response, stage="anonymous", user_id=None, old=None, code=None):
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), time.time()
        hashed = self.digest(token)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires<?", (now,))
            if old:
                conn.execute("DELETE FROM sessions WHERE token_hash=?", (old["token_hash"],))
            conn.execute("INSERT INTO sessions(token_hash,csrf,user_id,stage,expires,code_hash,code_expires,sent) VALUES(?,?,?,?,?,?,?,?)",
                         (hashed, csrf, user_id, stage, now + (self.ttl if stage == "authenticated" else 600),
                          self.digest(hashed + ":" + code) if code else None, now + 600 if code else None,
                          now if code else 0))
        response.set_cookie(COOKIE, token, max_age=self.ttl if stage == "authenticated" else 600,
                            secure=self.secure, httponly=True, samesite=self.samesite, path="/api/admin")
        result = {"stage": stage, "csrf": csrf}
        if stage == "anonymous":
            result["captcha"] = self.captcha({"token_hash": hashed})
        return result

    def captcha(self, session, refresh=False):
        now = time.time()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM sessions WHERE token_hash=? AND expires>?",
                               (session["token_hash"], now)).fetchone()
            if not row:
                raise HTTPException(401, "La sesión venció. Recargá el acceso.")
            if row["stage"] != "anonymous":
                raise HTTPException(400, "La verificación numérica corresponde al inicio de sesión.")
            if refresh or not row["captcha_hash"] or row["captcha_expires"] <= now:
                left, right = secrets.randbelow(10) + 1, secrets.randbelow(10) + 1
                challenge_id = uuid.uuid4().hex
                question = f"¿Cuánto es {left} + {right}?"
                expires = min(now + 300, row["expires"])
                encoded = self.digest(f"captcha:{row['token_hash']}:{challenge_id}:{left + right}")
                conn.execute("UPDATE sessions SET captcha_id=?,captcha_question=?,captcha_hash=?,captcha_expires=? WHERE token_hash=?",
                             (challenge_id, question, encoded, expires, row["token_hash"]))
            else:
                challenge_id, question, expires = row["captcha_id"], row["captcha_question"], row["captcha_expires"]
        return {"id": challenge_id, "question": question, "expires_in": max(0, int(expires - now))}

    def consume_captcha(self, session, challenge_id, answer):
        valid = False
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM sessions WHERE token_hash=? AND stage='anonymous' AND captcha_id=?",
                               (session["token_hash"], challenge_id)).fetchone()
            if row:
                if row["expires"] > time.time() and row["captcha_expires"] > time.time() and row["captcha_hash"] and re.fullmatch(r"[0-9]{1,2}", answer):
                    expected = self.digest(f"captcha:{row['token_hash']}:{challenge_id}:{int(answer)}")
                    valid = hmac.compare_digest(row["captcha_hash"], expected)
                # Consumir incluso una respuesta incorrecta; dos solicitudes no pueden reutilizarlo.
                conn.execute("UPDATE sessions SET captcha_id=NULL,captcha_question=NULL,captcha_hash=NULL,captcha_expires=0 WHERE token_hash=?",
                             (row["token_hash"],))
        return valid

    def session(self, request, required=False, superadmin=False):
        token = request.cookies.get(COOKIE, "")
        with self.db.connect() as conn:
            row = conn.execute("SELECT s.*, u.email,u.active,u.name,u.is_superadmin FROM sessions s LEFT JOIN users u ON s.user_id=u.id WHERE token_hash=? AND expires>?",
                               (self.digest(token), time.time())).fetchone()
        if not row or (row["user_id"] and not row["active"]):
            raise HTTPException(401, "La sesión venció. Volvé a ingresar.")
        if required and row["stage"] != "authenticated":
            raise HTTPException(401, "Completá los dos pasos de acceso.")
        if superadmin and not row["is_superadmin"]:
            raise HTTPException(403, "Esta operación requiere un superadministrador.")
        return dict(row)

    def protect(self, request, required=True, superadmin=False):
        row = self.session(request, required, superadmin)
        csrf = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(row["csrf"], csrf):
            raise HTTPException(403, "La solicitud de seguridad venció. Recargá el panel.")
        origin = request.headers.get("Origin")
        base = f"{request.url.scheme}://{request.url.netloc}"
        if origin and origin not in self.origins | {base}:
            raise HTTPException(403, "Origen de solicitud no permitido.")
        return row

    def limit(self, key, maximum, window):
        now, key = time.time(), self.digest(key)
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM limits WHERE at<?", (now - 86400,))
            count = conn.execute("SELECT COUNT(*) FROM limits WHERE key=? AND at>?", (key, now - window)).fetchone()[0]
            if count >= maximum:
                raise HTTPException(429, "Demasiados intentos. Esperá antes de volver a ingresar.", headers={"Retry-After": str(window)})
            conn.execute("INSERT INTO limits(key,at) VALUES(?,?)", (key, now))

    def login(self, request, response, email, password, captcha_id, captcha_answer):
        old = self.protect(request, False)
        ip = request.client.host if request.client else "?"
        self.limit("login-ip:" + ip, 5, 60)
        self.limit("login-email:" + email.strip().lower(), 10, 900)
        if not self.consume_captcha(old, captcha_id, captcha_answer):
            raise HTTPException(400, "La respuesta de seguridad es incorrecta o venció. Resolvé el nuevo cálculo.")
        with self.db.connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        verified = valid_password(user["password_hash"] if user else DUMMY_HASH, password)
        if not user or not verified or not user["active"]:
            self.db.audit("anonymous", "login.failed")
            raise HTTPException(401, "Correo o contraseña inválidos.")
        if old["stage"] == "pending" and time.time() - old["sent"] < 60:
            raise HTTPException(429, "Esperá un minuto antes de solicitar otro código.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            self.mailer(user["email"], code)
        except Exception:
            self.db.audit(user["email"], "mail.failed")
            raise HTTPException(503, "No se pudo enviar el código. Revisá la configuración de correo.") from None
        result = self.new_session(response, "pending", user["id"], old, code)
        self.db.audit(user["email"], "login.password_verified")
        return result

    def verify(self, request, response, code):
        old = self.protect(request, False)
        valid = False
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM sessions WHERE token_hash=?", (old["token_hash"],)).fetchone()
            if row and row["stage"] == "pending" and row["code_expires"] > time.time() and row["attempts"] < 5:
                valid = hmac.compare_digest(row["code_hash"] or "", self.digest(row["token_hash"] + ":" + code))
                if valid:
                    # Consumir dentro de la transacción; dos POST simultáneos no pueden reutilizarlo.
                    conn.execute("DELETE FROM sessions WHERE token_hash=?", (row["token_hash"],))
                else:
                    conn.execute("UPDATE sessions SET attempts=attempts+1 WHERE token_hash=?", (row["token_hash"],))
        if not valid:
            raise HTTPException(400, "Código inválido, vencido o bloqueado después de 5 intentos.")
        result = self.new_session(response, "authenticated", old["user_id"])
        self.db.audit(old["email"], "login.success")
        return {**result, "email": old["email"], "name": old["name"], "is_superadmin": bool(old["is_superadmin"])}

    def resend(self, request):
        old = self.protect(request, False)
        now = time.time()
        if old["stage"] != "pending" or old["attempts"] >= 5:
            raise HTTPException(400, "Volvé a ingresar tu correo y contraseña.")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM sessions WHERE token_hash=?", (old["token_hash"],)).fetchone()
            if not row or now - row["sent"] < 60:
                raise HTTPException(429, "Esperá un minuto antes de reenviar.")
            conn.execute("UPDATE sessions SET sent=? WHERE token_hash=?", (now, old["token_hash"]))
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            self.mailer(old["email"], code)
        except Exception:
            raise HTTPException(503, "No se pudo enviar el código. Probá nuevamente en un minuto.") from None
        with self.db.connect() as conn:
            conn.execute("UPDATE sessions SET code_hash=?,code_expires=? WHERE token_hash=? AND stage='pending'",
                         (self.digest(old["token_hash"] + ":" + code), min(old["expires"], now + 600), old["token_hash"]))
        return {"ok": True}

    def logout(self, request, response):
        old = self.protect(request, False)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (old["token_hash"],))
        response.delete_cookie(COOKIE, path="/api/admin", secure=self.secure, httponly=True, samesite=self.samesite)
        self.db.audit(old["email"] or "anonymous", "logout")
        return {"ok": True}
