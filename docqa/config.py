"""Central configuration, read from environment variables (or a .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".csv", ".xlsx", ".xls"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}  # photos of paper tickets
SUPPORTED_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS


@dataclass(frozen=True)
class Settings:
    model: str = os.getenv("DOCQA_MODEL", "claude-opus-5-5")
    effort: str = os.getenv("DOCQA_EFFORT", "medium")
    data_dir: Path = Path(os.getenv("DOCQA_DATA_DIR", "./data"))
    collection: str = os.getenv("DOCQA_COLLECTION", "documents")
    top_k: int = int(os.getenv("DOCQA_TOP_K", "6"))
    chunk_size: int = int(os.getenv("DOCQA_CHUNK_SIZE", "1000"))
    chunk_overlap: int = int(os.getenv("DOCQA_CHUNK_OVERLAP", "150"))
    rows_per_chunk: int = int(os.getenv("DOCQA_ROWS_PER_CHUNK", "20"))
    max_file_mb: int = int(os.getenv("DOCQA_MAX_FILE_MB", "20"))
    # Official manuals in laws/ can be large (the NJ manual is ~45 MB); user uploads keep the smaller limit.
    max_law_file_mb: int = int(os.getenv("DOCQA_MAX_LAW_FILE_MB", "100"))
    max_question_chars: int = int(os.getenv("DOCQA_MAX_QUESTION_CHARS", "2000"))
    # Chunks scoring above this cosine distance are treated as irrelevant.
    max_distance: float = float(os.getenv("DOCQA_MAX_DISTANCE", "0.75"))
    max_retrievals: int = int(os.getenv("DOCQA_MAX_RETRIEVALS", "2"))
    # Folder of law libraries: laws/<STATE CODE>/*.pdf|txt|csv|xlsx ; laws/ALL/ applies to every state.
    laws_dir: Path = Path(os.getenv("DOCQA_LAWS_DIR", "./laws"))


settings = Settings()
