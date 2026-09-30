"""Convierte el .docx en chunks con contexto de sección y construye el índice (embeddings + BM25)."""
import json
import re
import sys
from pathlib import Path

import numpy as np
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from config import DOCX_PATH, EMBED_MODEL, INDEX_DIR, MODEL_CACHE, VECTOR_BACKEND

CHUNK_TARGET = 900  # caracteres por chunk (aprox. 200-250 tokens)
CHUNK_MAX = 1400


def iter_blocks(doc):
    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, doc)
        elif child.tag.endswith("}tbl"):
            yield Table(child, doc)


def clean(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def table_to_text(tbl: Table) -> str:
    rows = []
    for r in tbl.rows:
        cells = []
        for c in r.cells:
            t = clean(c.text)
            if not cells or cells[-1] != t:  # celdas combinadas se repiten
                cells.append(t)
        rows.append(cells)
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    header = rows[0]
    if len(rows) > 1 and len(header) > 1:
        out = []
        for r in rows[1:]:
            pairs = [f"{h}: {v}" if h and h != v else v for h, v in zip(header, r) if v]
            out.append("- " + "; ".join(pairs))
        return "\n".join(out)
    return "\n".join("- " + " | ".join(c for c in r if c) for r in rows)


def extract_sections(path: Path):
    """Devuelve lista de (ruta_de_titulos, texto) respetando el orden del documento."""
    doc = Document(str(path))
    sections, crumbs, buf = [], {}, []
    skip = False  # anexos internos e índice no se indexan en el asistente público

    def crumb_str():
        return " > ".join(crumbs[k] for k in sorted(crumbs))

    def flush():
        text = "\n".join(buf).strip()
        if text and not skip:
            sections.append((crumb_str(), text))
        buf.clear()

    for b in iter_blocks(doc):
        if isinstance(b, Paragraph):
            text = clean(b.text)
            if not text:
                continue
            style = b.style.name if b.style is not None else ""
            m = re.match(r"Heading (\d)", style)
            if style == "Normal" and len(text) < 80 and text == text.upper() and re.search(r"[A-ZÁÉÍÓÚ]", text):
                # Etiqueta de sección (p. ej. "Z1 / MINAS", "ANEXO INTERNO / RAG")
                flush()
                crumbs.clear()
                skip = text.startswith("ANEXO INTERNO") or text == "ÍNDICE"
                crumbs[0] = text.split("·")[0].strip()
            elif style == "Title":
                continue
            elif m:
                flush()
                level = int(m.group(1))
                for k in [k for k in crumbs if k >= level]:
                    del crumbs[k]
                crumbs[level] = text
            else:
                buf.append(text)
        else:
            t = table_to_text(b)
            if t:
                buf.append(t)
    flush()
    return sections


def split_text(text: str):
    """Agrupa párrafos hasta ~CHUNK_TARGET, partiendo por oraciones si un párrafo es enorme."""
    units = []
    for para in text.split("\n"):
        if len(para) <= CHUNK_MAX:
            units.append(para)
        else:
            units.extend(s for s in re.split(r"(?<=[.!?])\s+", para) if s)
    chunks, cur = [], ""
    for u in units:
        if cur and len(cur) + len(u) > CHUNK_TARGET:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{u}" if cur else u
    if cur:
        chunks.append(cur)
    return chunks


def build_chunks(path: Path):
    chunks, carry = [], ""
    sections = extract_sections(path)
    for i, (crumb, text) in enumerate(sections):
        if carry:  # secciones diminutas se pegan a la siguiente
            text = f"{carry}\n{text}"
            carry = ""
        if len(text) < 200 and i + 1 < len(sections):
            carry = f"{crumb.split(' > ')[-1]}: {text}"
            continue
        for part in split_text(text):
            crumbs = crumb.split(" > ")
            zone = re.match(r"(Z\d) /", crumbs[0])
            card = next((m.group(1) for p in crumbs if (m := re.match(r"(O\d\d) ·", p))), "")
            chunks.append(
                {
                    "id": len(chunks),
                    "section": crumb or "Introducción",
                    "text": part,
                    "zone": zone.group(1) if zone else "",
                    "card": card,
                    "doc": path.stem,
                }
            )
    return chunks


def build_overview(chunks):
    """Catálogo compacto de zonas y oportunidades para tener siempre en el prompt."""
    zones, opps = [], []
    for c in chunks:
        for m in re.finditer(
            r"Zona de trabajo: (Z\d) · ([^;]+); Tesis comercial a investigar: ([^;]+?)\.?; Primera pregunta: (.+)", c["text"]
        ):
            zones.append(f"- {m.group(1)} {m.group(2)}: {m.group(3)}. Primera pregunta: {m.group(4).strip()}")
        m = re.match(r"(O\d\d) · (.+)", c["section"].split(" > ")[-1])
        if m:
            zn = re.search(r"ZONAS: ([^|]+)\| PRIORIDAD ESTRATÉGICA: (\w)", c["text"])
            biz = re.search(r"Cliente y negocio\. (.+?\.)", c["text"])
            if zn and biz:
                opps.append(
                    f"- {m.group(1)} {m.group(2)} | zonas: {zn.group(1).strip()} | nivel {zn.group(2)} | {biz.group(1)}"
                )
    return (
        "ZONAS DE TRABAJO (segmentación funcional propuesta por la guía, no zonificación legal):\n"
        + "\n".join(zones)
        + "\n\nFICHAS DE OPORTUNIDAD (conceptos a validar; nivel A = cercanía a demanda existente, B = producto y mercado por construir, C = alta complejidad):\n"
        + "\n".join(opps)
    )


def main():
    if not DOCX_PATH.exists():
        sys.exit(f"No se encuentra {DOCX_PATH}")
    chunks = build_chunks(DOCX_PATH)
    print(f"{len(chunks)} chunks; {sum(len(c['text']) for c in chunks)} caracteres")

    from fastembed import TextEmbedding

    model = TextEmbedding(EMBED_MODEL, cache_dir=str(MODEL_CACHE))
    docs = [f"{c['section']}\n{c['text']}" for c in chunks]
    emb = np.array(list(model.embed(docs, batch_size=32)), dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(INDEX_DIR / "embeddings.npy", emb.astype(np.float16))
    (INDEX_DIR / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    if VECTOR_BACKEND == "lancedb":
        from store import LanceBackend

        LanceBackend.build(chunks, emb)
        print("Índice LanceDB creado")
    overview = build_overview(chunks)
    (INDEX_DIR / "overview.txt").write_text(overview, encoding="utf-8")
    print(f"Catálogo: {overview.count(chr(10))} líneas")
    print(f"Índice guardado en {INDEX_DIR}")


if __name__ == "__main__":
    main()
