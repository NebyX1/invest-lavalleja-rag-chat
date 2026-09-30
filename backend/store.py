"""Almacenes intercambiables para la recuperación: NumPy en memoria (por defecto) o LanceDB embebido.

Contrato (`rank`): devuelve dos rankings ordenados de (id, puntaje), uno denso y otro léxico, con filtros
opcionales por metadatos. La fusión (RRF) vive en `rag.py` y es idéntica para ambos backends.
"""
import os
import re
from typing import Optional

import numpy as np

from config import INDEX_DIR
from lexical import BM25, tokenize

FILTER_FIELDS = ("zone", "card", "doc")
_SAFE_VALUE = re.compile(r"^[\w .\-]+$")
DENSE_MIN = 0.25  # similitud mínima para que un candidato denso cuente sin apoyo léxico
TABLE = "chunks"


def check_where(where: Optional[dict]) -> dict:
    where = where or {}
    for k, v in where.items():
        if k not in FILTER_FIELDS or not isinstance(v, str) or not _SAFE_VALUE.fullmatch(v):
            raise ValueError(f"Filtro inválido: {k}={v!r}")
    return where


class NumpyBackend:
    """Todo en RAM: ideal hasta algunas decenas de miles de fragmentos."""

    name = "numpy"

    def __init__(self, chunks):
        self.emb = np.load(INDEX_DIR / "embeddings.npy").astype(np.float32)
        self.bm25 = BM25([tokenize(f"{c['section']} {c['text']}") for c in chunks])
        self.meta = {f: np.array([c.get(f) or "" for c in chunks]) for f in FILTER_FIELDS}

    def rank(self, qvec, qtext, n=20, where=None):
        dense = self.emb @ qvec
        sparse = self.bm25.scores(tokenize(qtext))
        where = check_where(where)
        if where:
            mask = np.ones(len(dense), dtype=bool)
            for f, v in where.items():
                mask &= self.meta[f] == v
            dense = np.where(mask, dense, -1.0)
            sparse = np.where(mask, sparse, 0.0)
        d = [(int(i), float(dense[i])) for i in np.argsort(-dense)[:n] if sparse[i] > 0 or dense[i] > DENSE_MIN]
        s = [(int(i), float(sparse[i])) for i in np.argsort(-sparse)[:n] if sparse[i] > 0 or dense[i] > DENSE_MIN]
        return d, s

    def dense_scores(self, ids, qvec):
        return dict(zip(ids, (self.emb[ids] @ qvec).tolist()))


class LanceBackend:
    """LanceDB embebido: en disco, filtros por metadatos, índice de texto y vectorial (ANN) para escalar."""

    name = "lancedb"
    ANN_MIN_ROWS = 20_000  # por debajo de esto la búsqueda exacta es más rápida que un índice ANN

    def __init__(self, chunks=None):
        os.environ.setdefault("LANCE_LOG", "error")  # silencia avisos de deprecación por consulta
        import lancedb

        db = lancedb.connect(str(INDEX_DIR / "lance"))
        if TABLE not in db.table_names():
            raise RuntimeError("No existe el índice LanceDB: ejecutá backend/ingest.py (o el setup).")
        self.table = db.open_table(TABLE)

    @staticmethod
    def build(chunks, emb):
        os.environ.setdefault("LANCE_LOG", "error")
        import lancedb
        from lancedb.index import FTS

        db = lancedb.connect(str(INDEX_DIR / "lance"))
        rows = [
            {
                "id": c["id"],
                "zone": c.get("zone") or "",
                "card": c.get("card") or "",
                "doc": c.get("doc") or "",
                "text": f"{c['section']} {c['text']}",
                "vector": emb[i].astype(np.float32),
            }
            for i, c in enumerate(chunks)
        ]
        table = db.create_table(TABLE, rows, mode="overwrite")
        table.create_index(
            "text",
            config=FTS(language="Spanish", stem=True, remove_stop_words=True, ascii_folding=True, lower_case=True),
            replace=True,
        )
        if len(rows) >= LanceBackend.ANN_MIN_ROWS:
            table.create_index(metric="cosine", vector_column_name="vector", index_type="IVF_HNSW_SQ", replace=True)
        return table

    @staticmethod
    def _sql(where):
        return " AND ".join(f"{f} = '{v}'" for f, v in check_where(where).items())

    def rank(self, qvec, qtext, n=20, where=None):
        sql = self._sql(where)
        q = self.table.search(qvec.astype(np.float32)).metric("cosine").select(["id", "_distance"])
        if sql:
            q = q.where(sql, prefilter=True)
        d = [(r["id"], 1.0 - r["_distance"]) for r in q.limit(n).to_list()]
        d = [(i, s) for i, s in d if s > DENSE_MIN]

        fts_text = re.sub(r"[^\w\s]", " ", qtext)
        q = self.table.search(fts_text, query_type="fts").select(["id", "_score"])
        if sql:
            q = q.where(sql, prefilter=True)
        s = [(r["id"], r["_score"]) for r in q.limit(n).to_list()]
        return d, s

    def dense_scores(self, ids, qvec):
        if not ids:
            return {}
        rows = self.table.search().where(f"id IN ({','.join(str(int(i)) for i in ids)})").select(["id", "vector"]).limit(len(ids)).to_list()
        return {r["id"]: float(np.dot(r["vector"], qvec)) for r in rows}


def make_backend(name: str, chunks):
    if name == "lancedb":
        return LanceBackend(chunks)
    return NumpyBackend(chunks)
