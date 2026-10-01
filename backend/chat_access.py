"""Acceso desde el portal y cupos atómicos. Sólo persiste contadores, nunca conversaciones."""
import base64
import hashlib
import hmac
import json
import math
import sqlite3
import time
from contextlib import contextmanager
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel

from db_migrations import upgrade_database

LIMIT = 20
COOLDOWN = 600
SESSION_TTL = 30 * 86400


class BrowserSession(BaseModel):
    browser_id: UUID


class ChatAccess:
    def __init__(self, root, secret, origins, clock=time.time):
        self.path, self.secret, self.origins, self.clock = root / "chat-quota.sqlite3", secret, set(origins), clock
        root.mkdir(parents=True, exist_ok=True)
        upgrade_database(self.path, "quota")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def digest(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def origin(self, request):
        if request.headers.get("origin") not in self.origins:
            raise HTTPException(403, "Gianna está disponible únicamente desde la web de Invest Lavalleja.")

    def issue(self, browser, origin):
        payload = base64.urlsafe_b64encode(json.dumps({"id": str(browser), "origin": origin,
            "expires": self.clock() + SESSION_TTL}, separators=(",", ":")).encode()).decode().rstrip("=")
        return payload + "." + self.digest(payload)

    def authorize(self, request):
        self.origin(request)
        try:
            payload, signature = request.headers.get("x-chat-session", "").split(".")
            if not hmac.compare_digest(self.digest(payload), signature):
                raise ValueError()
            data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            browser = str(UUID(data["id"]))
            if data["origin"] != request.headers["origin"] or data["expires"] <= self.clock():
                raise ValueError()
            return browser
        except (ValueError, KeyError, TypeError):
            raise HTTPException(401, "La sesión de Gianna venció. Recargá la página.") from None

    def quota(self, ip, browser, consume=False):
        now = self.clock()
        keys = [self.digest("ip:" + ip), self.digest("browser:" + browser)]
        rejected = False
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM quotas WHERE updated<?", (now - SESSION_TTL,))
            rows = []
            for key in keys:
                row = db.execute("SELECT used,blocked_until FROM quotas WHERE key=?", (key,)).fetchone()
                used, until = row or (0, 0)
                if until and until <= now:
                    used, until = 0, 0
                rows.append([key, used, until])
            rejected = consume and any(until > now for _, _, until in rows)
            if consume and not rejected:
                for row in rows:
                    row[1] += 1
                    if row[1] >= LIMIT:
                        row[2] = now + COOLDOWN
                    db.execute("INSERT INTO quotas VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET used=excluded.used,blocked_until=excluded.blocked_until,updated=excluded.updated",
                               (*row, now))
            wait = max(0, math.ceil(max(until for _, _, until in rows) - now))
            result = {"limit": LIMIT, "remaining": 0 if wait else LIMIT - max(used for _, used, _ in rows),
                      "retry_after": wait}
        if rejected:
            raise HTTPException(429, "Alcanzaste las 20 consultas. Esperá 10 minutos para continuar.",
                                headers={"Retry-After": str(wait), "X-Chat-Remaining": "0", "X-Chat-Retry-After": str(wait)})
        return result
