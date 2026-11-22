"""Input and output safety checks that run outside the model."""
from __future__ import annotations

import re

from .config import settings

DISCLAIMER = (
    "This is general information drawn from the documents you loaded, not legal advice. "
    "Laws change and differ by place; check the official source or a lawyer before acting."
)

# Phrases typical of attempts to override the assistant's instructions.
_INJECTION = re.compile(
    r"(ignore (all|any|the|your) (previous|prior|above) (instructions|rules)"
    r"|disregard (the|your) (system|previous) (prompt|instructions)"
    r"|you are now (?!driving)"
    r"|reveal (your|the) (system )?prompt"
    r"|act as (an? )?(unfiltered|jailbroken)"
    r"|developer mode)",
    re.IGNORECASE,
)


class GuardrailViolation(ValueError):
    pass


def check_question(question: str) -> str:
    q = (question or "").strip()
    if not q:
        raise GuardrailViolation("Please type a question.")
    if len(q) > settings.max_question_chars:
        raise GuardrailViolation(
            f"The question is too long ({len(q)} characters). Keep it under {settings.max_question_chars}."
        )
    if _INJECTION.search(q):
        raise GuardrailViolation(
            "That looks like an attempt to change how the assistant works. Ask a question about your documents instead."
        )
    return q


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text or ""))


_CITE = re.compile(r"\[(\d+)\]")


def strip_invalid_citations(answer: str, n_context: int) -> tuple[str, list[int]]:
    """Drop citation markers that point at chunks that were never shown to the model."""
    used: list[int] = []

    def repl(m: re.Match) -> str:
        idx = int(m.group(1))
        if 1 <= idx <= n_context:
            if idx not in used:
                used.append(idx)
            return m.group(0)
        return ""

    return _CITE.sub(repl, answer), used
