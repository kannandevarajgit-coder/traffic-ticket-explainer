"""Split sections into overlapping chunks sized for embedding."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .config import settings
from .ingest import Section

_SEPARATORS = ["\n\n", "\n", ". ", " "]


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict


def _split(text: str, size: int, separators: list[str]) -> list[str]:
    """Recursive splitter: break on the coarsest separator that keeps pieces under `size`."""
    if len(text) <= size:
        return [text]
    if not separators:
        return [text[i : i + size] for i in range(0, len(text), size)]
    sep, rest = separators[0], separators[1:]
    parts = text.split(sep)
    if len(parts) == 1:
        return _split(text, size, rest)
    pieces, current = [], ""
    for part in parts:
        candidate = f"{current}{sep}{part}" if current else part
        if len(candidate) <= size:
            current = candidate
        else:
            if current:
                pieces.append(current)
            if len(part) > size:
                pieces.extend(_split(part, size, rest))
                current = ""
            else:
                current = part
    if current:
        pieces.append(current)
    return pieces


def split_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    size = size or settings.chunk_size
    overlap = settings.chunk_overlap if overlap is None else overlap
    text = re.sub(r"[ \t]+", " ", text).strip()
    pieces = _split(text, size, _SEPARATORS)
    if overlap <= 0 or len(pieces) < 2:
        return pieces
    # Prepend the tail of the previous piece so facts spanning a boundary are not lost.
    out = [pieces[0]]
    for prev, cur in zip(pieces, pieces[1:]):
        tail = prev[-overlap:]
        cut = tail.find(" ")
        tail = tail[cut + 1 :] if 0 <= cut < len(tail) - 1 else tail
        out.append(f"{tail} {cur}")
    return out


def chunk_sections(sections: list[Section]) -> list[Chunk]:
    chunks = []
    for s_idx, section in enumerate(sections):
        # Table blocks are already row-sized; keep them whole so rows are not cut.
        texts = [section.text] if section.metadata.get("type") == "table" else split_text(section.text)
        for c_idx, text in enumerate(texts):
            meta = dict(section.metadata, chunk=c_idx)
            digest = hashlib.sha1(
                f"{meta.get('source')}|{s_idx}|{c_idx}|{text}".encode()
            ).hexdigest()[:16]
            chunks.append(Chunk(id=digest, text=text, metadata=meta))
    return chunks


def cite(meta: dict) -> str:
    """Human-readable citation label for a chunk's metadata."""
    label = meta.get("source", "unknown")
    if "page" in meta:
        label += f", p. {meta['page']}"
    if "sheet" in meta:
        label += f", sheet {meta['sheet']}"
    if "rows" in meta:
        label += f", rows {meta['rows']}"
    return label
