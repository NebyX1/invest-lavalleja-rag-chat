"""Regresión real de recuperación: compara índices sin llamar al LLM ni enviar correo."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from rag import Retriever

QUERIES = ["oportunidades en el norte", "turismo Villa Serrana", "incentivos COMAP",
           "permisos para cámara de frío", "contactos institucionales", "servicios al agro",
           "José Pedro Varela", "O12", "zonas Z1 y Z5", "primera consulta para invertir"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    old = Retriever(args.original)
    new = Retriever(args.candidate, model=old.model, reranker=old.reranker)
    assert old.chunks == new.chunks, "Cambió el contenido del corpus"
    assert np.array_equal(np.load(args.original / "embeddings.npy"), np.load(args.candidate / "embeddings.npy")), "Cambiaron los embeddings"
    assert (args.original / "overview.txt").read_text(encoding="utf-8") == (args.candidate / "overview.txt").read_text(encoding="utf-8"), "Cambió el catálogo"
    for query in QUERIES:
        before, after = old.search(query, 8), new.search(query, 8)
        assert [h["id"] for h in before] == [h["id"] for h in after], f"Cambió el ranking: {query}"
        assert np.allclose([h["score"] for h in before], [h["score"] for h in after]), f"Cambió la similitud: {query}"
    assert old.lookup(["O12"], ["Z5"]) == new.lookup(["O12"], ["Z5"])
    assert [h["id"] for h in old.search("inversiones", where={"zone": "Z5"})] == [h["id"] for h in new.search("inversiones", where={"zone": "Z5"})]
    print(json.dumps({"ok": True, "chunks": len(new.chunks), "queries": len(QUERIES), "same_rankings": True}))


if __name__ == "__main__":
    main()
