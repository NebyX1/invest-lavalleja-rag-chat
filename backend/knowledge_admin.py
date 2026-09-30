"""Versiones inmutables: construir, validar y recién entonces cambiar la base activa."""
import asyncio
import hashlib
import json
import logging
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

from fastapi import HTTPException

from config import DOCX_PATH, EMBED_MODEL, INDEX_DIR, VECTOR_BACKEND
from knowledge_format import SCHEMA, export_docx, read_jsonl, write_jsonl

log = logging.getLogger(__name__)


class KnowledgeAdmin:
    def __init__(self, db, prepare_runtime, runtime_state):
        self.db, self.prepare_runtime, self.state = db, prepare_runtime, runtime_state
        self.root = db.root
        for folder in ("documents", "revisions", "uploads"):
            (self.root / folder).mkdir(exist_ok=True)
        self.task = None

    def recover(self):
        with self.db.connect() as conn:
            conn.execute("UPDATE jobs SET status='failed',message='El proceso se interrumpió. Reintentá la operación.',finished=? WHERE status IN ('queued','running')", (time.time(),))
            committed = {r[0] for r in conn.execute("SELECT id FROM revisions")}
            deleted_docs = [r[0] for r in conn.execute("SELECT id FROM documents WHERE deleted=1")]
        for folder in (self.root / "revisions").iterdir():
            if folder.is_dir() and folder.name not in committed:
                self.remove_tree(folder)
        for file in (self.root / "uploads").iterdir():
            if file.is_file():
                file.unlink()
        for doc_id in deleted_docs:
            self.remove_tree(self.root / "documents" / doc_id)

    def remove_tree(self, path, strict=False):
        resolved, root = Path(path).resolve(), self.root.resolve()
        if resolved == root or not resolved.is_relative_to(root):
            raise ValueError("Ruta de almacenamiento inválida.")
        if resolved.exists():
            shutil.rmtree(resolved, ignore_errors=not strict)

    def active_id(self):
        with self.db.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='active_revision'").fetchone()
        return row[0] if row else None

    def manifest(self, revision=None):
        revision = revision or self.active_id()
        if not revision:
            return {"id": None, "documents": [], "chunks": 0}
        if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{32}", revision):
            raise HTTPException(404, "Versión inexistente.")
        with self.db.connect() as conn:
            if not conn.execute("SELECT 1 FROM revisions WHERE id=?", (revision,)).fetchone():
                raise HTTPException(404, "Versión inexistente.")
        path = self.root / "revisions" / revision / "manifest.json"
        if not path.exists():
            raise HTTPException(404, "Versión inexistente.")
        return json.loads(path.read_text(encoding="utf-8"))

    def active_path(self):
        active = self.active_id()
        return self.root / "revisions" / active / "index" if active else None

    def bootstrap_legacy(self):
        # Adopta el índice que ya funciona sin volver a vectorizar ni alterar sus datos.
        if self.active_id() is not None or not (INDEX_DIR / "chunks.json").exists():
            return
        chunks = json.loads((INDEX_DIR / "chunks.json").read_text(encoding="utf-8"))
        if not chunks:
            return
        doc_id, revision = uuid.uuid4().hex, uuid.uuid4().hex
        folder = self.root / "documents" / doc_id
        folder.mkdir()
        title = "Guía de Inversiones de Lavalleja 2026"
        canonical = folder / "knowledge.jsonl"
        write_jsonl(canonical, {"type": "manifest", "schema": SCHEMA, "title": title,
                    "source": DOCX_PATH.name, "chunk_count": len(chunks)}, chunks)
        target = self.root / "revisions" / revision
        target.mkdir()
        shutil.copytree(INDEX_DIR, target / "index")
        document = {"id": doc_id, "name": DOCX_PATH.name, "title": title,
                    "sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
                    "chunks": len(chunks), "size": DOCX_PATH.stat().st_size if DOCX_PATH.exists() else canonical.stat().st_size,
                    "created": time.time()}
        manifest = {"id": revision, "documents": [document], "chunks": len(chunks),
                    "created": time.time(), "action": "importar índice existente", "backend": VECTOR_BACKEND,
                    "embedding_model": EMBED_MODEL}
        (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        with self.db.connect() as conn:
            conn.execute("INSERT INTO documents(id,name,title,sha256,chunks,size,created) VALUES(:id,:name,:title,:sha256,:chunks,:size,:created)", document)
            conn.execute("INSERT INTO settings(key,value) VALUES('active_revision',?)", (revision,))
            conn.execute("INSERT INTO revisions(id,created) VALUES(?,?)", (revision, manifest["created"]))
        self.db.audit("system", "knowledge.adopt", revision)

    def busy(self):
        with self.db.connect() as conn:
            return conn.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running')").fetchone() is not None

    def documents(self):
        active = {d["id"] for d in self.manifest()["documents"]}
        with self.db.connect() as conn:
            return [{**dict(r), "enabled": r["id"] in active} for r in
                    conn.execute("SELECT * FROM documents WHERE deleted=0 ORDER BY created DESC")]

    def document(self, doc_id):
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id=? AND deleted=0", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Documento inexistente.")
        return dict(row)

    def canonical_path(self, doc_id):
        self.document(doc_id)
        return self.root / "documents" / doc_id / "knowledge.jsonl"

    async def upload(self, source, name, title, actor, replace_id=None):
        if self.busy():
            raise HTTPException(409, "Ya hay una operación en curso.")
        old = self.document(replace_id) if replace_id else None
        doc_id = uuid.uuid4().hex
        folder = self.root / "documents" / doc_id
        folder.mkdir()
        try:
            canonical = folder / "knowledge.jsonl"
            if source.suffix.lower() == ".docx":
                # El nombre de origen preserva el campo doc del fragmentado existente.
                original = folder / name
                shutil.copyfile(source, original)
                _, chunks = await asyncio.to_thread(export_docx, original, canonical, title)
            elif source.suffix.lower() == ".jsonl":
                _, chunks = await asyncio.to_thread(read_jsonl, source)
                shutil.copyfile(source, canonical)
            else:
                raise ValueError("Solo se aceptan archivos .docx o .jsonl de Gianna.")
            item = {"id": doc_id, "name": name, "title": title or name,
                    "sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
                    "chunks": len(chunks), "size": source.stat().st_size, "created": time.time()}
            with self.db.connect() as conn:
                conn.execute("INSERT INTO documents(id,name,title,sha256,chunks,size,created) VALUES(:id,:name,:title,:sha256,:chunks,:size,:created)", item)
            active = [d["id"] for d in self.manifest()["documents"]]
            selected = [doc for doc in active if not old or doc != old["id"]]
            if not old or old["id"] in active:
                selected.append(doc_id)
            try:
                return self.schedule("actualizar documento" if old else "cargar documento", selected, actor,
                                     deleted=[old["id"]] if old else [])
            except Exception:
                with self.db.connect() as conn:
                    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
                raise
        except BaseException:
            self.remove_tree(folder)
            raise

    def schedule(self, action, selected, actor, deleted=(), restore=None):
        for doc_id in selected:
            self.document(doc_id)
        job_id = uuid.uuid4().hex
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running')").fetchone():
                raise HTTPException(409, "Ya hay una operación en curso.")
            conn.execute("INSERT INTO jobs(id,action,status,message,created,actor) VALUES(?,?,'queued','Preparando los documentos…',?,?)",
                         (job_id, action, time.time(), actor))
        self.task = asyncio.create_task(self._run(job_id, action, list(selected), actor, list(deleted), restore))
        return {"id": job_id, "status": "queued"}

    async def build(self, selected, output):
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).with_name("knowledge_cli.py")), "build", "--output", str(output),
            *(str(self.canonical_path(d)) for d in selected),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            _, error = await asyncio.wait_for(process.communicate(), timeout=1800)
            if process.returncode:
                # No exponer contenido del corpus ni configuración en la respuesta pública.
                log.error("Indexación fallida (%s): %s", process.returncode, error.decode(errors="replace")[-2000:])
                raise RuntimeError("No se pudo vectorizar. Revisá los modelos, el espacio en disco y los logs del servidor.")
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise

    async def _run(self, job_id, action, selected, actor, deleted, restore):
        revision = restore or uuid.uuid4().hex
        target = self.root / "revisions" / revision
        committed = False
        try:
            with self.db.connect() as conn:
                conn.execute("UPDATE jobs SET status='running',message='Vectorizando y validando la base…' WHERE id=?", (job_id,))
            if restore:
                manifest = self.manifest(restore)
                if manifest.get("backend") != VECTOR_BACKEND or manifest.get("embedding_model") != EMBED_MODEL:
                    raise ValueError("La versión utiliza otro modelo o almacén vectorial.")
            else:
                target.mkdir()
                await self.build(selected, target / "index")
                docs = [self.document(d) for d in selected]
                manifest = {"id": revision, "documents": docs, "created": time.time(), "action": action,
                            "chunks": sum(d["chunks"] for d in docs), "backend": VECTOR_BACKEND,
                            "embedding_model": EMBED_MODEL}
                (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            runtime = await self.prepare_runtime(target / "index")
            # El puntero y el resultado se confirman en la misma transacción persistente.
            with self.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('active_revision',?)", (revision,))
                conn.execute("INSERT OR IGNORE INTO revisions(id,created) VALUES(?,?)", (revision, manifest["created"]))
                for doc_id in deleted:
                    conn.execute("UPDATE documents SET deleted=1 WHERE id=?", (doc_id,))
                conn.execute("UPDATE jobs SET status='completed',message='La base está actualizada.',finished=?,revision=? WHERE id=?",
                             (time.time(), revision, job_id))
                conn.execute("INSERT INTO audit(at,actor,action,detail) VALUES(?,?,?,?)", (time.time(), actor, "knowledge." + action, revision))
            committed = True
            # Sin await entre commit y cambio: cada nueva consulta ve una versión completa.
            self.state.update(runtime)
            self.state["revision"] = revision
            for doc_id in deleted:
                self.remove_tree(self.root / "documents" / doc_id)
        except BaseException as exc:
            if not committed:
                message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "La operación se interrumpió. La base anterior sigue activa."
                with self.db.connect() as conn:
                    conn.execute("UPDATE jobs SET status='failed',message=?,finished=? WHERE id=?", (message[:300], time.time(), job_id))
                if not restore:
                    self.remove_tree(target)
                self.db.audit(actor, "knowledge.failed", job_id)
            if isinstance(exc, asyncio.CancelledError):
                raise
            log.exception("No se completó la operación de conocimiento %s", job_id)

    def set_enabled(self, doc_id, enabled, actor):
        self.document(doc_id)
        selected = [d["id"] for d in self.manifest()["documents"] if d["id"] != doc_id]
        if enabled:
            selected.append(doc_id)
        return self.schedule("activar documento" if enabled else "desactivar documento", selected, actor)

    def delete(self, doc_id, actor):
        self.document(doc_id)
        selected = [d["id"] for d in self.manifest()["documents"] if d["id"] != doc_id]
        return self.schedule("eliminar documento", selected, actor, deleted=[doc_id])

    def restore(self, revision, actor):
        manifest = self.manifest(revision)
        ids = [d["id"] for d in manifest["documents"]]
        for doc_id in ids:
            try:
                self.document(doc_id)
            except HTTPException:
                raise HTTPException(409, "Esta versión contiene un documento eliminado. Podés volver a cargarlo desde su respaldo.") from None
        return self.schedule("restaurar versión", ids, actor, restore=revision)

    def revisions(self):
        active = self.active_id()
        available = {d["id"] for d in self.documents()}
        items = []
        with self.db.connect() as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM revisions")]
        for revision in ids:
            m = self.manifest(revision)
            items.append({**m, "active": m["id"] == active,
                          "restorable": all(d["id"] in available for d in m["documents"])})
        return sorted(items, key=lambda m: m["created"], reverse=True)

    def prune(self, revision, actor):
        self.manifest(revision)
        if revision == self.active_id():
            raise HTTPException(409, "No podés eliminar la versión activa.")
        if self.busy() or self.state.get("inflight", 0):
            raise HTTPException(409, "Esperá a que terminen las operaciones y las consultas en curso.")
        try:
            self.remove_tree(self.root / "revisions" / revision, strict=True)
        except OSError:
            raise HTTPException(409, "No se pudo borrar la versión del disco. Esperá a que se libere y reintentá.") from None
        with self.db.connect() as conn:
            conn.execute("DELETE FROM revisions WHERE id=?", (revision,))
        self.db.audit(actor, "knowledge.prune", revision)

    def status(self):
        with self.db.connect() as conn:
            jobs = [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 12")]
        active = self.manifest()
        return {"active": active, "documents": self.documents(), "jobs": jobs,
                "busy": any(j["status"] in ("queued", "running") for j in jobs),
                "backend": VECTOR_BACKEND, "embedding_model": EMBED_MODEL}

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
