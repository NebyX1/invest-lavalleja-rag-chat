"""Compara los backends de recuperación: python scripts/compare_backends.py (requiere lancedb y el índice construido con VECTOR_BACKEND=lancedb)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
import rag

QUERIES = [
    "ventajas fiscales para una posada en Villa Serrana",
    "qué oportunidades hay en el norte",
    "permisos para una cámara de frío",
    "con quién hablo para empezar",
    "cuánto cuesta instalarme",
    "Poscosecha, medición y eficiencia en granos cómo entrar",
    "riesgos de invertir en Lavalleja",
    "estructura jurídica SRL SAS impuestos",
    "geoparque UNESCO Arequita",
    "exoneración de IRAE límites",
]


def load(name):
    rag.VECTOR_BACKEND = name
    return rag.Retriever()


numpy_r, lance_r = load("numpy"), load("lancedb")
overlaps, top1 = [], 0
for q in QUERIES:
    a = [h["id"] for h in numpy_r.search(q, 8)]
    b = [h["id"] for h in lance_r.search(q, 8)]
    overlaps.append(len(set(a) & set(b)) / 8)
    top1 += a[0] == b[0]
    print(f"{len(set(a) & set(b))}/8 solapan | top1 {'=' if a[0] == b[0] else '≠'} | {q}")
print(f"\nSolape medio top-8: {sum(overlaps) / len(overlaps):.0%}; mismo primer resultado: {top1}/{len(QUERIES)}")

for name, r in (("numpy", numpy_r), ("lancedb", lance_r)):
    t = time.perf_counter()
    for i, q in enumerate(QUERIES * 3):
        r.search(f"{q} {i}", 8)
    print(f"{name}: {(time.perf_counter() - t) / (len(QUERIES) * 3) * 1000:.1f} ms por búsqueda")

for name, r in (("numpy", numpy_r), ("lancedb", lance_r)):
    hits = r.search("permisos y requisitos", 5, where={"zone": "Z2"})
    print(f"{name} con filtro zone=Z2 →", [(h["id"], h["zone"]) for h in hits])
