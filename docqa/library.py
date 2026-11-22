"""Per-state law libraries and per-user ticket uploads, kept apart with metadata filters."""
from __future__ import annotations

from pathlib import Path

from .chunking import chunk_sections
from .config import SUPPORTED_EXTENSIONS, settings
from .ingest import IngestionError, load_document
from .store import VectorStore

# Jurisdictions offered in the dropdown. Add a code here and a laws/<CODE>/ folder to support another one.
JURISDICTIONS = {
    "CA": "California",
    "NJ": "New Jersey",
    "NY": "New York State",
    "NYC": "New York City",
    "VT": "Vermont",
    "SAMPLE": "Sample State (fictional demo data)",
}
# A city also uses its state's laws: NYC questions search NYC rules and New York State law.
PARENTS = {"NYC": ["NY"]}
ALL = "ALL"
SAMPLE = "SAMPLE"


def state_label(code: str) -> str:
    return JURISDICTIONS.get(code, code)


def jurisdiction_chain(code: str) -> list[str]:
    """The jurisdiction itself, then any parents (NYC -> NY)."""
    return [code, *PARENTS.get(code, [])]


def save_law_file(state: str, filename: str, data: bytes, laws_dir: Path | None = None) -> Path:
    """Store an official law document in laws/<state>/ so it is indexed for that state."""
    from .ingest import validate_upload

    validate_upload(filename, len(data), settings.max_law_file_mb)
    folder = (laws_dir or settings.laws_dir) / state
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / Path(filename).name
    path.write_bytes(data)
    return path


def library_states(laws_dir: Path | None = None) -> list[str]:
    """State codes that have a law folder with at least one supported file."""
    root = laws_dir or settings.laws_dir
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and d.name.upper() != ALL and any(
            f.suffix.lower() in SUPPORTED_EXTENSIONS for f in d.iterdir()
        ):
            out.append(d.name.upper())
    return out


def scope_filter(state: str, session_id: str | None) -> dict:
    """Search only this state's laws, laws marked ALL, and this user's own uploads."""
    laws = {"$and": [{"kind": "law"}, {"state": {"$in": [*jurisdiction_chain(state), ALL]}}]}
    if not session_id:
        return laws
    return {"$or": [laws, {"session": session_id}]}


def index_state_library(store: VectorStore, state: str, laws_dir: Path | None = None) -> dict:
    """Index every file in laws/<state>/ (plus parent jurisdictions and laws/ALL/) not indexed yet."""
    root = laws_dir or settings.laws_dir
    report = {"indexed": [], "skipped": [], "errors": []}
    tags = [*jurisdiction_chain(state), ALL]
    for folder, tag in ((root / t, t) for t in tags):
        if not folder.is_dir():
            continue
        done = set(store.sources({"$and": [{"kind": "law"}, {"state": tag}]}))
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() not in SUPPORTED_EXTENSIONS or f.name.startswith("."):
                continue
            if f.name in done:
                report["skipped"].append(f.name)
                continue
            try:
                sections = load_document(
                    f.name, f.read_bytes(), {"kind": "law", "state": tag}, settings.max_law_file_mb
                )
                n = store.add(chunk_sections(sections))
                report["indexed"].append(f"{f.name} ({n} chunks)")
            except IngestionError as exc:
                report["errors"].append(str(exc))
    return report


def add_user_document(store: VectorStore, filename: str, data: bytes, state: str, session_id: str) -> int:
    """Index a user's own upload (their ticket, a notice from the court) for their session only."""
    meta = {"kind": "ticket", "state": state, "session": session_id}
    return index_user_sections(store, load_document(filename, data, meta), session_id)


def index_user_sections(store: VectorStore, sections: list, session_id: str) -> int:
    """Index sections already loaded with ticket metadata (lets the caller also read their text)."""
    chunks = chunk_sections(sections)
    # Keep session uploads distinct from library files with the same name.
    for c in chunks:
        c.id = f"{session_id[:8]}-{c.id}"
    return store.add(chunks)


def clear_user_documents(store: VectorStore, session_id: str) -> None:
    store.delete({"session": session_id})
