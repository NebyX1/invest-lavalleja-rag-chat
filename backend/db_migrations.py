"""Migraciones SQLite versionadas; adopta las bases existentes sin borrar datos."""
import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def statements(script):
    buffer = ""
    for char in script:
        buffer += char
        if char == ";" and sqlite3.complete_statement(buffer):
            yield buffer
            buffer = ""
    if buffer.strip():
        raise ValueError("La migración contiene una sentencia SQL incompleta.")


def upgrade_database(path, kind, directory=MIGRATIONS_DIR):
    path, directory = Path(path), Path(directory)
    migrations = []
    for file in sorted(directory.glob(f"*_{kind}.sql")):
        match = re.fullmatch(rf"(\d+)_{re.escape(kind)}\.sql", file.name)
        if match:
            migrations.append((int(match[1]), file))
    if not migrations or [version for version, _ in migrations] != list(range(1, len(migrations) + 1)):
        raise ValueError(f"Faltan migraciones consecutivas para la base {kind}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("PRAGMA user_version").fetchone()[0]
        if current > migrations[-1][0]:
            raise RuntimeError("La base utiliza una versión más nueva que este backend.")
        for version, file in migrations:
            if version <= current:
                continue
            for statement in statements(file.read_text(encoding="utf-8")):
                db.execute(statement)
            db.execute(f"PRAGMA user_version={version}")
        db.commit()
        return migrations[-1][0]
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def upgrade_all(root, directory=MIGRATIONS_DIR):
    root = Path(root)
    return {
        "admin": upgrade_database(root / "admin.sqlite3", "admin", directory),
        "quota": upgrade_database(root / "chat-quota.sqlite3", "quota", directory),
    }
