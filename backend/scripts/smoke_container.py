"""Prueba Docker sin secretos reales. Conserva el contenedor solo con --keep."""
import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def request(path, body=None, headers=None):
    req = urllib.request.Request("http://127.0.0.1:8021" + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="invest-backend:production")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    name = "gianna-smoke-" + uuid.uuid4().hex[:8]
    volume = name + "-data"
    try:
        docker("run", "-d", "--name", name, "-p", "127.0.0.1:8021:8010", "-v", volume + ":/data",
               "-e", "OLLAMA_API_KEY=smoke-placeholder", "-e", "OLLAMA_MODEL=smoke-placeholder",
               "-e", "ADMIN_SECRET_KEY=smoke-secret-with-at-least-32-characters",
               "-e", "ADMIN_EMAIL=qa@example.test", "-e", "ADMIN_PASSWORD=Only-for-tests-2026!", args.image)
        for _ in range(60):
            try:
                status, raw = request("/api/health")
                if status == 200:
                    health = json.loads(raw)
                    assert health["ok"] and health["knowledge_ready"] is False
                    break
            except (OSError, TimeoutError):
                pass
            time.sleep(1)
        else:
            raise RuntimeError("El contenedor no inició")
        for path in ("/", "/admin", "/admin/login", "/docs", "/redoc", "/openapi.json"):
            assert request(path)[0] == 404, path
        assert request("/api/admin/knowledge")[0] == 401
        assert request("/api/chat", {"messages": [{"role": "user", "content": "Hola"}]})[0] == 403
        origin = "http://127.0.0.1:8080"
        status, raw = request("/api/chat/session", {"browser_id": str(uuid.uuid4())}, {"Origin": origin})
        assert status == 200
        token = json.loads(raw)["token"]
        assert request("/api/chat", {"messages": [{"role": "user", "content": "Hola"}]},
                       {"Origin": origin, "X-Chat-Session": token})[0] == 503
        check = "from pathlib import Path; import os,sqlite3; assert Path.home().is_dir() and os.access(Path.home(),os.W_OK); p=Path('/data/admin/admin.sqlite3'); db=sqlite3.connect(p); assert db.execute('PRAGMA user_version').fetchone()[0]==3; assert db.execute('select count(*) from users where is_superadmin=1 and name!=\"\"').fetchone()[0]==1; quota=sqlite3.connect('/data/admin/chat-quota.sqlite3'); assert quota.execute('PRAGMA user_version').fetchone()[0]==1; assert not Path('/app/backend/.env').exists(); assert not Path('/app/.env').exists(); print('persistencia y aislamiento correctos')"
        assert "correctos" in docker("exec", name, "python", "-c", check)
        docker("restart", name)
        for _ in range(60):
            try:
                if request("/api/health")[0] == 200:
                    break
            except (OSError, TimeoutError):
                pass
            time.sleep(1)
        else:
            raise RuntimeError("El contenedor no reinició")
        assert "correctos" in docker("exec", name, "python", "-c", check)
        assert docker("exec", name, "id", "-u") == "10001"
        print(json.dumps({"ok": True, "container": name, "volume": volume, "restart": True, "nonroot": True, "private_admin": True}))
    finally:
        if not args.keep:
            subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Este volumen tiene un nombre aleatorio creado exclusivamente por esta prueba.
            subprocess.run(["docker", "volume", "rm", volume], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
