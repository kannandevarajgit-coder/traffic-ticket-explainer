import io

import pandas as pd
import pytest

from docqa.chunking import chunk_sections, cite, split_text
from docqa.ingest import IngestionError, load_document
from conftest import ROOT


def test_txt_and_chunking():
    data = (ROOT / "laws/SAMPLE/sample_state_driver_handbook.txt").read_bytes()
    sections = load_document("handbook.txt", data, {"state": "SAMPLE"})
    chunks = chunk_sections(sections)
    assert len(chunks) > 3
    assert all(len(c.text) <= 1000 + 200 for c in chunks)
    assert chunks[0].metadata["state"] == "SAMPLE"


def test_csv_rows_keep_headers():
    data = (ROOT / "laws/SAMPLE/sample_state_fine_schedule.csv").read_bytes()
    sections = load_document("fines.csv", data)
    assert "violation_code: VC 22350" in sections[0].text
    assert sections[0].metadata["rows"].startswith("2-")


def test_excel_all_sheets():
    data = (ROOT / "laws/SAMPLE/sample_state_point_system.xlsx").read_bytes()
    sections = load_document("points.xlsx", data)
    assert {s.metadata["sheet"] for s in sections} == {"Suspension thresholds", "Insurance effects"}


def test_pdf_pages():
    data = (ROOT / "sample_docs/sample_ticket.pdf").read_bytes()
    sections = load_document("ticket.pdf", data)
    assert sections[0].metadata["page"] == 1
    assert "VC 22356" in sections[0].text
    assert cite(sections[0].metadata) == "ticket.pdf, p. 1"


@pytest.mark.parametrize("name,data,msg", [
    ("virus.exe", b"x", "not supported"),
    ("empty.txt", b"", "empty"),
    ("bad.pdf", b"not a pdf", "Could not open PDF"),
])
def test_rejects_bad_files(name, data, msg):
    with pytest.raises(IngestionError, match=msg):
        load_document(name, data)


def test_split_overlap():
    text = " ".join(f"word{i}" for i in range(600))
    parts = split_text(text, size=500, overlap=50)
    assert len(parts) > 1
    assert parts[1].split()[0] in parts[0]
