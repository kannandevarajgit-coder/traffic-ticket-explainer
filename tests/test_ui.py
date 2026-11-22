"""Drives the real Streamlit page headlessly with the fake Claude client."""
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from docqa import llm
from docqa.config import settings
from fake_llm import FakeClient
from test_ticket import TICKET

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def isolated_data(tmp_path):
    old = settings.data_dir
    object.__setattr__(settings, "data_dir", tmp_path)  # Settings is frozen; tests only
    st.cache_resource.clear()
    yield tmp_path
    object.__setattr__(settings, "data_dir", old)
    st.cache_resource.clear()
    llm.set_client(None)


def script():
    return {
        "ticket": lambda kw: TICKET,
        "planner": lambda kw: {"intent": "documents", "standalone_question": "explain my ticket",
                               "queries": ["VC 22356 speeding fine points"], "reply": ""},
        "retriever": lambda kw: "Done.",
        "reasoner": lambda kw: "Your speeding ticket costs $238 to $490 [1].",
        "validator": lambda kw: {"verdict": "grounded", "unsupported_claims": [], "followup_queries": [],
                                 "unsafe": False},
    }


def test_full_flow_sample_ticket_to_cited_answer(isolated_data):
    llm.set_client(FakeClient(script()))
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    assert at.chat_input[0].disabled  # nothing works until a state is chosen

    sample =next(b for b in at.button if "sample" in b.label.lower())
    sample.click().run()
    assert not at.exception
    assert any("Your ticket" in m.value for m in at.markdown)
    assert any(b.label == "Explain my ticket" for b in at.button)
    assert not at.chat_input[0].disabled

    next(b for b in at.button if b.label == "Explain my ticket").click().run()
    assert not at.exception
    answer = [m.value for m in at.markdown if "costs" in m.value]
    assert answer and "\\$238" in answer[0]  # dollars escaped so they are not rendered as maths
    assert any(b.label.startswith("Compare my options") for b in at.button)  # follow-up suggestions
