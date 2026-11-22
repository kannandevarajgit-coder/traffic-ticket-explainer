import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def store(tmp_path):
    from docqa.store import VectorStore
    return VectorStore(path=str(tmp_path / "chroma"), collection="test")


@pytest.fixture
def sample_store(store):
    from docqa.library import index_state_library
    report = index_state_library(store, "SAMPLE", ROOT / "laws")
    assert not report["errors"], report
    return store
