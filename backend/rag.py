"""Recuperación híbrida liviana: embeddings densos (ONNX/CPU) + BM25, fusionados con RRF."""
import json
import math
import re
import unicodedata
from collections import Counter
from functools import lru_cache

import numpy as np

from config import EMBED_MODEL, INDEX_DIR, MODEL_CACHE

STOPWORDS = set(
    "a al algo ante como con como cual cuales cuando de del donde el ella ellos en es esa ese eso esta este esto "
    "hay la las le les lo los mas me mi mis muy no nos o para pero por que se si sin sobre su sus te tu tus un "
    "una uno unos y ya yo son ser fue puede pueden hacer tiene tienen quiero quisiera".split()
)


def tokenize(text: str):
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return [t[:6] for t in re.findall(r"[a-z0-9]+", text) if t not in STOPWORDS and len(t) > 1]


# Intenciones coloquiales que el vocabulario de la guía nombra distinto
EXPANSIONS = {
    r"\b(hablar|comunic\w*|contact\w*|llamar|tel[eé]fono|mail|correo|escribir|direcci[oó]n|oficina|atenci[oó]n|ventanilla)\b":
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


class BM25:
    def __init__(self, docs, k1=1.4, b=0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=np.float32)
        self.avg = float(self.len.mean()) or 1.0
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query_tokens):
        s = np.zeros(len(self.tf), dtype=np.float32)
        for t in set(query_tokens):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(t)
                if f:
                    s[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return s


class Retriever:
    def __init__(self):
        self.chunks = json.loads((INDEX_DIR / "chunks.json").read_text(encoding="utf-8"))
        self.emb = np.load(INDEX_DIR / "embeddings.npy").astype(np.float32)
        self.bm25 = BM25([tokenize(f"{c['section']} {c['text']}") for c in self.chunks])
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

    def search(self, query: str, k: int = 6):
        query = expand(query)
        dense = self.emb @ self._embed(query)
        sparse = self.bm25.scores(tokenize(query))
        fused: dict[int, float] = {}
        for ranking in (np.argsort(-dense)[:20], np.argsort(-sparse)[:20]):
            for rank, i in enumerate(ranking):
                if sparse[i] > 0 or dense[i] > 0.25:
                    fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (60 + rank)
        top = sorted(fused, key=fused.get, reverse=True)[:k]
        return [{**self.chunks[i], "score": float(dense[i])} for i in top]

    def search_multi(self, query: str, k: int = 8):
        """Consultas con varias preguntas: recupera por oración y intercala los resultados."""
        parts = [p.strip() for p in re.split(r"[.?!¿\n]+", query) if len(p.split()) >= 3]
        if len(parts) < 2:
            return self.search(query, k)
        lists = [self.search(q, k) for q in [query, *parts]]
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
