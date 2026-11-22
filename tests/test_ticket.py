from datetime import date

import pytest

from docqa import llm
from docqa.agents import answer_question
from docqa.library import scope_filter
from docqa.ticket import (
    TicketInfo,
    calendar_file,
    days_left,
    deadline_label,
    extract_ticket,
    parse_date,
)
from fake_llm import FakeClient

TICKET = {
    "is_ticket": True,
    "violations": [{"code": "VC 22356", "description": "Speed 49 in a 30 zone", "fine": ""},
                   {"code": "VC 23123.5", "description": "Hand-held cell phone", "fine": "$162"}],
    "violation_date": "2026-11-14", "due_date": "2026-12-29", "total_due": "",
    "court": "Sample County Traffic Court, 100 Court Plaza", "location": "Main St & 3rd Ave", "must_appear": False,
}


@pytest.fixture(autouse=True)
def reset_client():
    yield
    llm.set_client(None)


def test_extract_ticket_wraps_text_and_uses_ticket_agent():
    client = FakeClient({"ticket": lambda kw: TICKET})
    llm.set_client(client)
    info = extract_ticket("Violation 1: VC 22356 ... Respond on or before: 12/29/2026")
    assert info.violations[0].code == "VC 22356"
    role, kw = client.calls[0]
    assert role == "ticket"
    assert kw["messages"][0]["content"].startswith("<ticket>")
    assert kw["output_config"]["effort"] == "low"


def test_parse_date_accepts_iso_and_us_formats():
    assert parse_date("2026-12-29") == date(2026, 12, 29)
    assert parse_date("12/29/2026") == date(2026, 12, 29)
    assert parse_date("") is None
    assert parse_date("next Tuesday") is None


@pytest.mark.parametrize("days,color", [(-3, "red"), (0, "red"), (5, "red"), (14, "orange"), (40, "green")])
def test_deadline_colours(days, color):
    label, c = deadline_label(days)
    assert c == color and label


def test_days_left():
    assert days_left(date(2026, 12, 29), today=date(2026, 11, 22)) == 37


def test_calendar_file_is_valid_all_day_event_with_reminders():
    ics = calendar_file(date(2026, 12, 29), TicketInfo(**TICKET))
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "DTSTART;VALUE=DATE:20261229" in ics and "DTEND;VALUE=DATE:20261230" in ics
    assert ics.count("BEGIN:VALARM") == 2
    assert "Sample County Traffic Court\\, 100 Court Plaza" in ics  # commas escaped


def test_on_step_reports_each_agent_live(sample_store):
    client = FakeClient({
        "planner": lambda kw: {"intent": "documents", "standalone_question": "speeding fine",
                               "queries": ["speeding fine points"], "reply": ""},
        "retriever": lambda kw: "Done.",
        "reasoner": lambda kw: "Speeding 1-15 over costs $238 [1].",
        "validator": lambda kw: {"verdict": "grounded", "unsupported_claims": [], "followup_queries": [],
                                 "unsafe": False},
    })
    llm.set_client(client)
    seen = []
    res = answer_question(sample_store, "speeding fine?", where=scope_filter("SAMPLE", None),
                          state_name="Sample State", on_step=lambda s: seen.append(s["agent"]))
    assert res["status"] == "answered"
    assert seen == ["Guardrail", "Planner", "Retriever", "Reasoner", "Validator", "Finalize"]


def test_broken_progress_callback_does_not_break_answer(sample_store):
    llm.set_client(FakeClient({
        "planner": lambda kw: {"intent": "greeting", "standalone_question": "hi", "queries": [], "reply": "Hello!"},
    }))

    def boom(step):
        raise RuntimeError("display failed")

    res = answer_question(sample_store, "hi", on_step=boom)
    assert res["answer"] == "Hello!"
