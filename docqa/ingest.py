"""Load PDF, TXT, CSV and Excel files into plain-text sections with source metadata."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import IMAGE_EXTENSIONS, SUPPORTED_EXTENSIONS, settings


class IngestionError(ValueError):
    """Raised when a file cannot be accepted or parsed."""


@dataclass
class Section:
    """A unit of source text before chunking: one PDF page, one text file, or one block of table rows."""

    text: str
    metadata: dict = field(default_factory=dict)


def validate_upload(filename: str, size_bytes: int, max_mb: int | None = None) -> str:
    """Check extension and size. Returns the lowercase extension."""
    max_mb = max_mb or settings.max_file_mb
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise IngestionError(
            f"'{filename}' is not supported. Use one of: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
    if size_bytes == 0:
        raise IngestionError(f"'{filename}' is empty.")
    if size_bytes > max_mb * 1024 * 1024:
        raise IngestionError(f"'{filename}' is larger than the {max_mb} MB limit.")
    return ext


def _load_pdf(data: bytes, filename: str) -> list[Section]:
    import pymupdf

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # corrupt or encrypted file
        raise IngestionError(f"Could not open PDF '{filename}': {exc}") from exc
    sections = []
    with doc:
        if doc.needs_pass:
            raise IngestionError(f"'{filename}' is password protected.")
        for page_no, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:
                sections.append(Section(text, {"source": filename, "page": page_no, "type": "pdf"}))
    if not sections:
        raise IngestionError(
            f"No text found in '{filename}'. It may be a scanned image; OCR is not supported."
        )
    return sections


def _load_txt(data: bytes, filename: str) -> list[Section]:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = data.decode(encoding).strip()
            break
        except UnicodeDecodeError:
            continue
    if not text:
        raise IngestionError(f"'{filename}' has no text.")
    return [Section(text, {"source": filename, "type": "txt"})]


def _frame_to_sections(df: pd.DataFrame, filename: str, sheet: str | None) -> list[Section]:
    """Turn table rows into 'column: value' text so they embed and read well.

    Each block of rows repeats the column names, so a chunk is understandable on its own.
    """
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.empty:
        return []
    df.columns = [str(c).strip() for c in df.columns]
    sections = []
    n = settings.rows_per_chunk
    for start in range(0, len(df), n):
        block = df.iloc[start : start + n]
        lines = []
        for idx, row in block.iterrows():
            cells = "; ".join(f"{col}: {row[col]}" for col in df.columns if pd.notna(row[col]))
            lines.append(f"Row {int(idx) + 2}: {cells}")  # +2 = header row + 1-based
        header = f"Table from {filename}" + (f", sheet '{sheet}'" if sheet else "")
        header += f". Columns: {', '.join(df.columns)}."
        meta = {
            "source": filename,
            "type": "table",
            "rows": f"{start + 2}-{start + len(block) + 1}",
        }
        if sheet:
            meta["sheet"] = sheet
        sections.append(Section(header + "\n" + "\n".join(lines), meta))
    return sections


def _load_csv(data: bytes, filename: str) -> list[Section]:
    try:
        df = pd.read_csv(io.BytesIO(data), sep=None, engine="python")
    except Exception as exc:
        raise IngestionError(f"Could not parse CSV '{filename}': {exc}") from exc
    sections = _frame_to_sections(df, filename, None)
    if not sections:
        raise IngestionError(f"'{filename}' has no rows.")
    return sections


def _load_excel(data: bytes, filename: str) -> list[Section]:
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    except Exception as exc:
        raise IngestionError(f"Could not parse Excel file '{filename}': {exc}") from exc
    sections = []
    for name, df in sheets.items():
        sections.extend(_frame_to_sections(df, filename, str(name)))
    if not sections:
        raise IngestionError(f"'{filename}' has no rows in any sheet.")
    return sections


_LOADERS = {
    ".pdf": _load_pdf,
    ".txt": _load_txt,
    ".csv": _load_csv,
    ".xlsx": _load_excel,
    ".xls": _load_excel,
}


def load_document(
    filename: str, data: bytes, extra_meta: dict | None = None, max_mb: int | None = None
) -> list[Section]:
    """Validate and parse one uploaded file. `extra_meta` (state, kind, session) is added to every section."""
    ext = validate_upload(filename, len(data), max_mb)
    if ext in IMAGE_EXTENSIONS:
        sections = _load_image(data, Path(filename).name, ext)
    else:
        sections = _LOADERS[ext](data, Path(filename).name)
    for s in sections:
        s.metadata.update(extra_meta or {})
    return sections


def _load_image(data: bytes, filename: str, ext: str) -> list[Section]:
    """Photo of a paper ticket: Claude reads it and returns a transcription."""
    from .llm import LLMError, transcribe_image

    media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[ext]
    try:
        text = transcribe_image(data, media)
    except LLMError as exc:
        raise IngestionError(f"Could not read the image '{filename}': {exc}") from exc
    if not text.strip():
        raise IngestionError(f"No readable text found in '{filename}'.")
    return [Section(text, {"source": filename, "type": "image"})]
