"""Ticket reader agent: pulls the key facts off an uploaded ticket, plus deadline helpers.

Only what is printed on the ticket is extracted. Points, totals and options come from the law
documents through the normal question flow, so nothing here is guessed.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field

from . import llm, prompts


class Violation(BaseModel):
    code: str = Field(description="Violation code or section exactly as printed, e.g. 'VC 22350'; empty if none")
    description: str = Field(description="Short plain description as printed on the ticket")
    fine: str = Field(description="Fine amount printed for this violation, e.g. '$238'; empty if not printed")


class TicketInfo(BaseModel):
    is_ticket: bool = Field(description="True if the text is a traffic or parking ticket, citation or court notice")
    violations: list[Violation]
    violation_date: str = Field(description="Date of the violation as YYYY-MM-DD; empty if not printed")
    due_date: str = Field(description="Date to pay or respond by, as YYYY-MM-DD; empty if not printed")
    total_due: str = Field(description="Total amount due if printed; empty otherwise")
    court: str = Field(description="Court or agency name and address if printed; empty otherwise")
    location: str = Field(description="Where the violation happened if printed; empty otherwise")
    must_appear: bool = Field(description="True only if the ticket says a court appearance is mandatory")


MAX_TICKET_CHARS = 12000


def extract_ticket(text: str) -> TicketInfo:
    """Read the user's ticket text and return its key facts. Raises llm.LLMError on API problems."""
    prompt = f"<ticket>\n{text[:MAX_TICKET_CHARS]}\n</ticket>"
    return llm.structured(prompts.TICKET, prompt, TicketInfo, effort="low", max_tokens=3000)


def parse_date(value: str) -> date | None:
    """Accept YYYY-MM-DD (what we ask for) and MM/DD/YYYY (what tickets often print)."""
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def days_left(due: date, today: date | None = None) -> int:
    return (due - (today or date.today())).days


def deadline_label(days: int) -> tuple[str, str]:
    """Text and colour for the deadline badge."""
    if days < 0:
        return f"Overdue by {-days} day{'s' if days != -1 else ''}", "red"
    if days == 0:
        return "Due today", "red"
    if days <= 7:
        return f"{days} day{'s' if days != 1 else ''} left", "red"
    if days <= 21:
        return f"{days} days left", "orange"
    return f"{days} days left", "green"


def _ics_escape(text: str) -> str:
    return re.sub(r"([,;\\])", r"\\\1", text).replace("\n", "\\n")


def calendar_file(due: date, info: TicketInfo) -> str:
    """An .ics event on the due date with reminders 7 days and 1 day before."""
    codes = ", ".join(v.code or v.description for v in info.violations) or "traffic ticket"
    desc = f"Pay or respond to your ticket ({codes})."
    if info.court:
        desc += f" Court: {info.court}."
    desc += " Created by Traffic Ticket Explainer. General information, not legal advice."
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    end = date.fromordinal(due.toordinal() + 1)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Traffic Ticket Explainer//EN", "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@traffic-ticket-explainer", f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{due:%Y%m%d}", f"DTEND;VALUE=DATE:{end:%Y%m%d}",
        f"SUMMARY:{_ics_escape('Traffic ticket due: ' + codes)}",
        f"DESCRIPTION:{_ics_escape(desc)}",
    ]
    for trigger in ("-P7D", "-P1D"):
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:{trigger}",
                  "DESCRIPTION:Traffic ticket due soon", "END:VALARM"]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"
