"""Estado administrativo persistente, separado del índice y del agente."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from db_migrations import upgrade_database


class AdminDB:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "admin.sqlite3"
        upgrade_database(self.path, "admin")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def audit(self, actor, action, detail=""):
        import time
        with self.connect() as db:
            db.execute("INSERT INTO audit(at,actor,action,detail) VALUES(?,?,?,?)",
                       (time.time(), actor, action, detail))
