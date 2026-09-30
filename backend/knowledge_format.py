"""Formato transportable de conocimiento. No resume ni cambia los chunks existentes."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

from ingest import build_chunks, build_overview

SCHEMA = "gianna.knowledge.v1"
MAX_CHUNKS = 30_000
MAX_TEXT = 30_000_000


def validate_chunks(chunks):
    if not chunks or len(chunks) > MAX_CHUNKS:
        raise ValueError("El documento debe tener entre 1 y 30000 fragmentos.")
    chars = 0
    for i, c in enumerate(chunks):
        if not isinstance(c, dict):
            raise ValueError("Fragmento inválido.")
        for field in ("section", "text", "zone", "card", "doc"):
            if not isinstance(c.get(field), str):
                raise ValueError(f"Falta el campo de texto {field}.")
        if not c["text"].strip() or len(c["text"]) > 100_000 or len(c["section"]) > 2000:
            raise ValueError("Fragmento vacío o demasiado grande.")
        if re.search(r"ANEXO\s+INTERNO", c["section"], re.I):
            raise ValueError("El archivo incluye un anexo interno; retiralo antes de publicarlo.")
        if c["zone"] and not re.fullmatch(r"Z\d+", c["zone"]):
            raise ValueError("Código de zona inválido.")
        if c["card"] and not re.fullmatch(r"O\d+", c["card"]):
            raise ValueError("Código de ficha inválido.")
        if not re.fullmatch(r"[\w .-]{1,240}", c["doc"]):
            raise ValueError("Nombre de fuente inválido.")
        c["id"] = i
        chars += len(c["text"])
    if chars > MAX_TEXT:
        raise ValueError("El documento contiene demasiado texto.")
    return chunks


def export_docx(source: Path, destination: Path, title=None):
    # DOCX es un ZIP: limitar expansión antes de que python-docx lo abra.
    with zipfile.ZipFile(source) as archive:
        files = archive.infolist()
        if len(files) > 3000 or sum(f.file_size for f in files) > 50_000_000:
            raise ValueError("El Word supera el límite de contenido descomprimido.")
        if "word/document.xml" not in archive.namelist():
            raise ValueError("El archivo no es un documento Word válido.")
    chunks = build_chunks(source)
    doc_name = re.sub(r"[^\w .-]", "_", source.stem)[:240] or "documento"
    for c in chunks:
        c["doc"] = doc_name
    validate_chunks(chunks)
    manifest = {"type": "manifest", "schema": SCHEMA,
                "title": title or source.stem, "source": source.name,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "chunk_count": len(chunks)}
    write_jsonl(destination, manifest, chunks)
    return manifest, chunks


def write_jsonl(destination, manifest, chunks):
    with Path(destination).open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(manifest, ensure_ascii=False) + "\n")
        for c in chunks:
            f.write(json.dumps({"type": "chunk", **c}, ensure_ascii=False) + "\n")


def read_jsonl(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        try:
            manifest = json.loads(next(f))
        except (StopIteration, json.JSONDecodeError) as e:
            raise ValueError("El JSONL no tiene una cabecera válida.") from e
        if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA or manifest.get("type") != "manifest":
            raise ValueError(f"Se requiere el formato {SCHEMA}.")
        chunks = []
        for line in f:
            if not line.strip():
                continue
            try:
                c = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError("Una línea del JSONL es inválida.") from e
            if not isinstance(c, dict) or c.get("type") != "chunk":
                raise ValueError("Cada línea de contenido debe ser un fragmento.")
            chunks.append({k: c.get(k) for k in ("id", "section", "text", "zone", "card", "doc")})
            if len(chunks) > MAX_CHUNKS:
                raise ValueError("Demasiados fragmentos.")
    validate_chunks(chunks)
    if manifest.get("chunk_count") != len(chunks):
        raise ValueError("La cantidad de fragmentos no coincide con la cabecera.")
    # El catálogo siempre se deriva del contenido validado, nunca de instrucciones externas.
    return manifest, chunks


def overview_for(chunks):
    overview = build_overview(chunks)
    seen = set()
    return "\n".join(line for line in overview.splitlines()
                     if not line.startswith("- ") or (line not in seen and not seen.add(line)))
