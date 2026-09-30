"""Recuperación híbrida: embeddings densos (ONNX/CPU) + léxica, fusionadas con RRF. El almacén es intercambiable."""
import json
import re
from functools import lru_cache

import numpy as np

from config import EMBED_MODEL, INDEX_DIR, MODEL_CACHE, VECTOR_BACKEND
from lexical import tokenize  # noqa: F401  (reexportado para tools.py)
from store import make_backend

# Intenciones coloquiales que el vocabulario de la guía nombra distinto
EXPANSIONS = {
    r"\b(habl\w*|comunic\w*|contact\w*|llam\w*|tel[eé]fono|mail|correo|escribir|direcci[oó]n|oficina|atenci[oó]n|ventanilla)\b":
        "contactos canales institucionales publicados teléfono correo dirección",
    r"\b(cu[aá]nto cuesta|precio|costo|presupuesto|inversi[oó]n m[ií]nima)\b": "costos presupuesto defendible cajas escenarios",
    r"\b(pasos|c[oó]mo empiezo|c[oó]mo empezar|proceso|tr[aá]mite)\b": "ruta de la primera consulta a una inversión evaluable expediente",
    r"\b(invertir|inversi[oó]n|rubros?|sectores?|oportunidades?|negocios?|emprender|proyectos?)\b": "fichas de oportunidad conceptos para validar cartera prioridad nivel A",
    r"\b(norte|noreste|nordeste|noroeste)\b": "José Pedro Varela Batlle y Ordóñez Zapicán Mariscala Pirarajá zonas Z4 Z5 Z6",
    r"\b(sur|sureste|suroeste)\b": "Solís de Mataojo Aguas Blancas Z2 Minas sur",
    r"\b(sierras?|turismo|tur[ií]stic\w*|alojamiento|posada|hotel\w*|caba[nñ]as?)\b": "Villa Serrana Penitente Arequita experiencias hospitalidad geoparque Z3 Z7",
    r"\b(agro|campo|rural|ganader\w*|arroz|granos?|forestaci[oó]n|madera)\b": "servicios al agro ganaderos granos forestación Z4 Z5 Z6",
    r"\b(impuestos?|fiscal\w*|exoneraci[oó]n|incentivos?|beneficios?)\b": "promoción de inversiones COMAP decreto 329/025 IRAE exoneración",
}


def expand(query: str) -> str:
    extra = [v for pat, v in EXPANSIONS.items() if re.search(pat, query.lower())]
    return f"{query} {' '.join(extra)}" if extra else query


class Retriever:
    def __init__(self):
        self.chunks = json.loads((INDEX_DIR / "chunks.json").read_text(encoding="utf-8"))
        self.backend = make_backend(VECTOR_BACKEND, self.chunks)
        self.cards: dict[str, list[int]] = {}
        self.zones: dict[str, list[int]] = {}
        for c in self.chunks:
            parts = c["section"].split(" > ")
            for p in parts:
                if m := re.match(r"(O\d\d) ·", p):
                    self.cards.setdefault(m.group(1), []).append(c["id"])
            if m := re.match(r"(Z\d) /", parts[0]):
                self.zones.setdefault(m.group(1), []).append(c["id"])
        from fastembed import TextEmbedding

        self.model = TextEmbedding(EMBED_MODEL, cache_dir=str(MODEL_CACHE), threads=2)
        self._embed = lru_cache(maxsize=256)(self._embed_uncached)
        self._embed("warmup")

    def _embed_uncached(self, text: str):
        v = np.array(next(iter(self.model.embed([text]))), dtype=np.float32)
        return v / np.linalg.norm(v)

    def search(self, query: str, k: int = 6, where: dict | None = None):
        """Búsqueda híbrida con fusión RRF. `where` filtra por metadatos (zone, card, doc)."""
        query = expand(query)
        qv = self._embed(query)
        dense, sparse = self.backend.rank(qv, query, 20, where)
        fused: dict[int, float] = {}
        for ranking in (dense, sparse):
            for rank, (i, _) in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank)
        top = sorted(fused, key=fused.get, reverse=True)[:k]
        scores = self.backend.dense_scores(top, qv)
        return [{**self.chunks[i], "score": scores.get(i, 0.0)} for i in top]

    def search_multi(self, query: str, k: int = 8, where: dict | None = None):
        """Consultas con varias preguntas: recupera por oración y intercala los resultados."""
        parts = [p.strip() for p in re.split(r"[.?!¿\n]+", query) if len(p.split()) >= 3]
        if len(parts) < 2:
            return self.search(query, k, where)
        lists = [self.search(q, k, where) for q in [query, *parts]]
        out, seen = [], set()
        for rank in range(k):
            for lst in lists:
                if rank < len(lst) and lst[rank]["id"] not in seen:
                    seen.add(lst[rank]["id"])
                    out.append(lst[rank])
        return out[:k]

    def lookup(self, codes, zones, per_card=3, per_zone=4):
        """Trae directamente las fichas (O##) y zonas (Z#) sobre las que se profundiza."""
        ids = [i for c in codes for i in self.cards.get(c, [])[:per_card]]
        ids += [i for z in zones for i in self.zones.get(z, [])[:per_zone]]
        return [{**self.chunks[i], "score": 1.0} for i in ids]

    def gather(self, queries, codes=(), zones=(), k=8):
        """Fichas/zonas en foco primero, luego los mejores resultados de cada consulta intercalados."""
        out = self.lookup(codes, zones, per_zone=4 if len(zones) == 1 else 2)
        n_focus = len(out)
        seen = {h["id"] for h in out}
        lists = [self.search_multi(q, k) for q in queries]
        for rank in range(k):
            for lst in lists:
                if rank < len(lst) and lst[rank]["id"] not in seen:
                    seen.add(lst[rank]["id"])
                    out.append(lst[rank])
        return out[: n_focus + k]
