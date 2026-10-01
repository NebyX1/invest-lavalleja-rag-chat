import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from admin_runtime import RuntimeLock
from db_migrations import MIGRATIONS_DIR, upgrade_all, upgrade_database

BACKEND = Path(__file__).resolve().parents[1]


def command(tmp_path, *args):
    env = {**os.environ, "ADMIN_DATA_DIR": str(tmp_path / "admin"),
           "INDEX_DIR": str(tmp_path / "legacy"), "MODEL_CACHE": str(tmp_path / "models"),
           "ADMIN_SECRET_KEY": "operations-test-secret-" * 3, "ADMIN_COOKIE_SECURE": "false",
           "ADMIN_EMAIL": "", "ADMIN_PASSWORD": "", "OLLAMA_API_KEY": "test-placeholder",
           "OLLAMA_MODEL": "test-placeholder"}
    return subprocess.run([sys.executable, "-m", "manage", *args], cwd=BACKEND, env=env,
                          capture_output=True, text=True, timeout=30)


def test_migrations_adopt_legacy_and_preserve_quotas(tmp_path):
    with sqlite3.connect(tmp_path / "admin.sqlite3") as db:
        db.executescript((MIGRATIONS_DIR / "001_admin.sql").read_text())
        db.execute("INSERT INTO users VALUES('legacy','legacy@example.test','existing-hash',1,1)")
    with sqlite3.connect(tmp_path / "chat-quota.sqlite3") as db:
        db.executescript((MIGRATIONS_DIR / "001_quota.sql").read_text())
        db.execute("INSERT INTO quotas VALUES('hashed-id',19,0,123)")
    assert upgrade_all(tmp_path) == {"admin": 3, "quota": 1}
    assert upgrade_all(tmp_path) == {"admin": 3, "quota": 1}
    with sqlite3.connect(tmp_path / "admin.sqlite3") as db:
        assert db.execute("SELECT name,is_superadmin,password_hash FROM users").fetchone() == (
            "legacy@example.test", 1, "existing-hash")
    with sqlite3.connect(tmp_path / "chat-quota.sqlite3") as db:
        assert db.execute("SELECT used FROM quotas").fetchone()[0] == 19


def test_newer_schema_is_rejected(tmp_path):
    path = tmp_path / "admin.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(RuntimeError, match="más nueva"):
        upgrade_database(path, "admin")
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99


def test_failed_migration_rolls_back(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_admin.sql").write_text("CREATE TABLE marker(id INTEGER);\nSELECT missing_column;\n")
    path = tmp_path / "broken.sqlite3"
    with pytest.raises(sqlite3.Error):
        upgrade_database(path, "admin", migrations)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("SELECT name FROM sqlite_master WHERE name='marker'").fetchone() is None


def test_cli_migrate_seed_and_create_roles(tmp_path):
    result = command(tmp_path, "db", "upgrade", "-d", "migrations")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"admin": 3, "quota": 1}
    password = "Only-for-cli-tests-2026!"
    for name, email, role in [("Responsable", "super@example.test", "true"), ("Editor", "editor@example.test", "false")]:
        result = command(tmp_path, "create-admin", name, email, password, role)
        assert result.returncode == 0, result.stderr
        assert password not in result.stdout + result.stderr
    for _ in range(2):
        result = command(tmp_path, "seed-data")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"versions": {"admin": 3, "quota": 1},
                                            "admin_created": False, "knowledge_ready": False, "chunks": 0}
    with sqlite3.connect(tmp_path / "admin" / "admin.sqlite3") as db:
        assert db.execute("SELECT name,is_superadmin FROM users ORDER BY created").fetchall() == [
            ("Responsable", 1), ("Editor", 0)]
        assert all(row[0] != password for row in db.execute("SELECT password_hash FROM users"))


def test_cli_first_account_and_runtime_lock(tmp_path):
    result = command(tmp_path, "create-admin", "Editor", "editor@example.test", "Only-for-cli-tests-2026!", "false")
    assert result.returncode == 1 and "primer administrador" in result.stderr
    with RuntimeLock(tmp_path / "admin" / "runtime.lock"):
        result = command(tmp_path, "db", "upgrade")
        assert result.returncode == 1 and "volumen ya está en uso" in result.stderr


def test_asgi_keeps_one_worker_and_configured_proxy(monkeypatch):
    import asgi
    import uvicorn
    calls = []
    monkeypatch.setenv("PROXY_TRUSTED_IPS", "192.0.2.0/24")
    monkeypatch.setattr(uvicorn, "run", lambda app, **options: calls.append((app, options)))
    asgi.main(["--host", "127.0.0.1", "--port", "8015", "--reload"])
    assert calls[0][0] == "main:app"
    assert calls[0][1] == {"host": "127.0.0.1", "port": 8015, "workers": 1,
                         "reload": True, "proxy_headers": True, "forwarded_allow_ips": "192.0.2.0/24"}
