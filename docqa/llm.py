"""Claude client wrapper: one place for model settings, refusal handling and API errors."""
from __future__ import annotations

import logging
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from .config import settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# Server-side refusal fallback: if a safety classifier declines, the API retries on a fallback model.
_BETAS = ["server-side-fallback-2026-07-01"]


class LLMError(RuntimeError):
    """A user-presentable failure talking to the model."""


class Refused(LLMError):
    """The model declined the request on safety grounds."""


_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        import os
        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            raise LLMError(
                "No Anthropic API key found. Set ANTHROPIC_API_KEY in your .env file or Streamlit secrets."
            )
        try:
            _client = anthropic.Anthropic(max_retries=3, timeout=120.0)
        except anthropic.AnthropicError as exc:
            raise LLMError(
                "No Anthropic API key found. Set ANTHROPIC_API_KEY in your .env file or Streamlit secrets."
            ) from exc
    return _client


def set_client(client: Any) -> None:
    """Swap in a fake client (used by tests)."""
    global _client
    _client = client


def _common(effort: str | None) -> dict:
    return {
        "model": settings.model,
        "betas": _BETAS,
        "fallbacks": "default",
        "output_config": {"effort": effort or settings.effort},
    }


def _check(response) -> None:
    if response.stop_reason == "refusal":
        raise Refused("The model declined to answer this request.")
    if response.stop_reason == "max_tokens":
        log.warning("Response hit max_tokens and may be truncated")


def _wrap_errors(fn):
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LLMError:
            raise
        except anthropic.AuthenticationError as exc:
            raise LLMError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("The API key has no access to this model, or the account has no credit.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Rate limited by the Anthropic API. Wait a minute and try again.") from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"The request was rejected by the API: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"The Anthropic API returned an error ({exc.status_code}). Try again.") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Anthropic API. Check the network connection.") from exc

    return inner


@_wrap_errors
def structured(system: str, prompt: str, schema: type[T], effort: str | None = None,
               max_tokens: int = 8000) -> T:
    """One call that returns a validated Pydantic object."""
    response = get_client().beta.messages.parse(
        **_common(effort),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=schema,
    )
    _check(response)
    parsed = response.parsed_output
    if parsed is None:
        raise LLMError("The model returned output that did not match the expected format.")
    return parsed


@_wrap_errors
def tool_turn(system: str, messages: list[dict], tools: list[dict], effort: str | None = None,
              max_tokens: int = 4000):
    """One step of a tool-use loop. Returns the raw response; the caller runs the tools."""
    response = get_client().beta.messages.create(
        **_common(effort),
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        tools=tools,
        tool_choice={"type": "auto"},
    )
    _check(response)
    return response


@_wrap_errors
def text(system: str, prompt: str, effort: str | None = None, max_tokens: int = 8000) -> str:
    """One call that returns plain text."""
    response = get_client().beta.messages.create(
        **_common(effort),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    _check(response)
    return "".join(b.text for b in response.content if b.type == "text").strip()


@_wrap_errors
def transcribe_image(data: bytes, media_type: str) -> str:
    """Read a photo of a traffic ticket and return its text."""
    import base64

    response = get_client().beta.messages.create(
        **_common("low"),
        max_tokens=4000,
        system="You transcribe photos of traffic tickets and citations. Output only the text you can read, "
               "keeping field labels (violation code, description, date, court, fine, due date). "
               "Write [unreadable] for parts you cannot read. Do not add explanations.",
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                          "data": base64.standard_b64encode(data).decode()}},
            {"type": "text", "text": "Transcribe this ticket."},
        ]}],
    )
    _check(response)
    return "".join(b.text for b in response.content if b.type == "text").strip()
