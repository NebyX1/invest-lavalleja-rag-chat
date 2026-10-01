"""Verifica cupos, IP del proxy y almacenamiento contra los contenedores reales de QA."""
import json
import sqlite3
import urllib.error
import urllib.request
from uuid import uuid4

ORIGIN = "http://127.0.0.1:18080"


def post(base, path, body=None, token=None, fake_ip=None):
    headers = {"Origin": ORIGIN, "Content-Type": "application/json"}
    if token: headers["X-Chat-Session"] = token
    if fake_ip: headers["X-Forwarded-For"] = fake_ip
    req = urllib.request.Request(base + path, data=json.dumps(body or {}).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, response.headers, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read().decode()


base = "http://frontend"
browser = str(uuid4())
code, _, raw = post(base, "/api/chat/session", {"browser_id": browser})
assert code == 200
token = json.loads(raw)["token"]
body = {"messages": [{"role": "user", "content": "Consulta privada de QA que no debe guardarse"}]}
for count in range(20):
    status, headers, text = post(base, "/api/chat", body, token, f"198.51.100.{count + 1}")
    assert status == 200, (count, status)
    assert "event: token" in text and "event: tools" in text and "event: error" not in text
    assert headers["X-Chat-Remaining"] == str(19 - count)
assert headers["X-Chat-Retry-After"] == "600"
status, headers, _ = post(base, "/api/chat", body, token)
assert status == 429 and 0 < int(headers["Retry-After"]) <= 600
# Otra sesión conserva el límite de IP, aunque intente falsear X-Forwarded-For.
_, _, raw = post(base, "/api/chat/session", {"browser_id": str(uuid4())})
assert json.loads(raw)["remaining"] == 0
assert post(base, "/api/chat", body, json.loads(raw)["token"], "203.0.113.99")[0] == 429
# Misma sesión desde otra IP (loopback) conserva el límite del navegador.
assert post("http://127.0.0.1:8010", "/api/chat", body, token)[0] == 429
quota_db = sqlite3.connect("/data/admin/chat-quota.sqlite3")
assert [row[1] for row in quota_db.execute("PRAGMA table_info(quotas)")] == ["key", "used", "blocked_until", "updated"]
assert all(len(row[0]) == 64 for row in quota_db.execute("SELECT key FROM quotas"))
admin_db = sqlite3.connect("/data/admin/admin.sqlite3")
assert not {"messages", "conversations", "chats"} & {row[0] for row in admin_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
print(json.dumps({"accepted": 20, "next_request": 429, "cooldown": 600, "ip_and_browser": True,
                  "forwarded_header_spoof_rejected": True, "conversation_tables": False}))
