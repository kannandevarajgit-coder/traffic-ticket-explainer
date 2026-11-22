from docqa.library import add_user_document, clear_user_documents, index_state_library, library_states, scope_filter
from conftest import ROOT


def test_library_indexes_once(sample_store):
    report = index_state_library(sample_store, "SAMPLE", ROOT / "laws")
    assert report["indexed"] == []
    assert len(report["skipped"]) == 3


def test_library_states():
    assert "SAMPLE" in library_states(ROOT / "laws")


def test_search_finds_relevant_rule(sample_store):
    hits = sample_store.search("what happens if I miss the court due date", 3, scope_filter("SAMPLE", None))
    assert any("40508" in h.text or "due date" in h.text for h in hits)


def test_state_scope_excludes_other_states(sample_store):
    assert sample_store.search("red light fine", 3, scope_filter("CA", None)) == []


def test_user_upload_is_private_to_session(sample_store):
    data = (ROOT / "sample_docs/sample_ticket.pdf").read_bytes()
    add_user_document(sample_store, "ticket.pdf", data, "SAMPLE", "session-a")
    mine = sample_store.search("citation number", 20, scope_filter("SAMPLE", "session-a"))
    theirs = sample_store.search("citation number", 20, scope_filter("SAMPLE", "session-b"))
    assert any(h.metadata.get("kind") == "ticket" for h in mine)
    assert not any(h.metadata.get("kind") == "ticket" for h in theirs)
    clear_user_documents(sample_store, "session-a")
    mine = sample_store.search("citation number", 20, scope_filter("SAMPLE", "session-a"))
    assert not any(h.metadata.get("kind") == "ticket" for h in mine)
