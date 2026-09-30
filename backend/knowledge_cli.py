"""Conversión e indexación aisladas del proceso del chat."""
import argparse
import json
from pathlib import Path

from config import EMBED_MODEL, MODEL_CACHE, VECTOR_BACKEND
from knowledge_format import export_docx, overview_for, read_jsonl, MAX_CHUNKS, MAX_TEXT


def build_index(sources, destination):
    import numpy as np
    from fastembed import TextEmbedding
    chunks = []
    for source in sources:
        _, items = read_jsonl(source)
        for c in items:
            chunks.append({**c, "id": len(chunks)})
    if len(chunks) > MAX_CHUNKS or sum(len(c["text"]) for c in chunks) > MAX_TEXT:
        raise ValueError("La base completa supera los límites de contenido.")
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    (destination / "overview.txt").write_text(overview_for(chunks), encoding="utf-8")
    if not chunks:
        return
    model = TextEmbedding(EMBED_MODEL, cache_dir=str(MODEL_CACHE), threads=2)
    docs = [f"{c['section']}\n{c['text']}" for c in chunks]
    emb = np.array(list(model.embed(docs, batch_size=32)), dtype=np.float32)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    if not np.isfinite(emb).all() or (norms == 0).any():
        raise ValueError("El modelo generó vectores inválidos.")
    emb /= norms
    np.save(destination / "embeddings.npy", emb.astype(np.float16))
    if VECTOR_BACKEND == "lancedb":
        from store import LanceBackend
        LanceBackend.build(chunks, emb, destination)
    print(f"Índice validado: {len(chunks)} fragmentos", flush=True)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="Word → JSONL público")
    export.add_argument("source", type=Path)
    export.add_argument("destination", type=Path)
    build = sub.add_parser("build", help="JSONL → índice existente de Gianna")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("sources", nargs="*", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        _, chunks = export_docx(args.source, args.destination)
        print(f"Exportado: {len(chunks)} fragmentos -> {args.destination}")
    else:
        build_index(args.sources, args.output)


if __name__ == "__main__":
    main()
