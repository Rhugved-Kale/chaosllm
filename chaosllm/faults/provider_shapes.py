"""Pinned, provider-accurate synthetic error shapes.

DESIGN.md 4.2: "Every synthetic error mimics the real provider's error shape
(status, JSON body, headers like retry-after) so SDK retry logic reacts
exactly as it would in prod." That fidelity is the point, so every shape
here is either taken verbatim from the provider's docs or, where the docs
only describe a scenario rather than give a literal string, clearly marked
as representative. Field names, status codes, and header names are the load-
bearing part (they drive SDK retry/backoff behavior); exact message wording
is not.

Per CLAUDE.md: provider error shapes live only in this file. Do not inline
one anywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ErrorShape:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# OpenAI
#
# Envelope confirmed from the openai-python SDK source (_client.py
# OpenAI._make_status_error): `data = body.get("error", body)`, which only
# makes sense if the wire body is `{"error": {...}}`. Field names
# (message/type/param/code) confirmed from _exceptions.py APIError parsing.
# https://developers.openai.com/api/docs/guides/error-codes
#
# Rate-limit headers confirmed from:
# https://developers.openai.com/api/docs/guides/rate-limits
# OpenAI does NOT document a retry-after header on 429s (confirmed absent
# from that page); it points integrators at x-ratelimit-reset-requests
# instead and recommends exponential backoff. Do not add a retry-after
# header to the OpenAI shapes, that header only applies to Anthropic below.
# ---------------------------------------------------------------------------


def openai_error(status: int, *, retry_after_s: int | None = None) -> ErrorShape:
    """A synthetic OpenAI-shaped error for status in {429, 500, 503}.

    `retry_after_s`, when given, overrides the default reset window on a 429
    (e.g. so `rate_limit_burst` can report the real window remaining). OpenAI
    does not document a `retry-after` header, so this sets
    `x-ratelimit-reset-requests` instead, matching what it actually returns.
    """
    if status == 429:
        reset_s = retry_after_s if retry_after_s is not None else 20
        return ErrorShape(
            status=429,
            body={
                "error": {
                    "message": ("Rate limit reached for requests. Please try again later."),
                    "type": "requests",
                    "param": None,
                    "code": "rate_limit_exceeded",
                }
            },
            headers={
                "x-ratelimit-limit-requests": "3500",
                "x-ratelimit-remaining-requests": "0",
                "x-ratelimit-reset-requests": f"{reset_s}s",
            },
        )
    if status in (500, 503):
        return ErrorShape(
            status=status,
            body={
                "error": {
                    "message": (
                        "The server had an error while processing your request. Sorry about that!"
                    ),
                    "type": "server_error",
                    "param": None,
                    "code": None,
                }
            },
            headers={},
        )
    raise ValueError(f"no pinned OpenAI shape for status {status}")


def openai_context_length_exceeded(*, limit: int = 8192, requested: int = 10402) -> ErrorShape:
    """OpenAI's context_length_exceeded shape (400, invalid_request_error).

    Widely and consistently documented (OpenAI cookbook, platform docs, years
    of unchanged behavior): type=invalid_request_error, code=
    context_length_exceeded, param="messages".
    """
    return ErrorShape(
        status=400,
        body={
            "error": {
                "message": (
                    f"This model's maximum context length is {limit} tokens. "
                    f"However, your messages resulted in {requested} tokens. "
                    "Please reduce the length of the messages."
                ),
                "type": "invalid_request_error",
                "param": "messages",
                "code": "context_length_exceeded",
            }
        },
        headers={},
    )


# ---------------------------------------------------------------------------
# Anthropic
#
# Envelope and status -> type mapping confirmed verbatim from:
# https://platform.claude.com/docs/en/api/errors
# retry-after and anthropic-ratelimit-* headers confirmed from:
# https://platform.claude.com/docs/en/api/rate-limits
# ("If you exceed any of the rate limits you will get a 429 error ...
# along with a retry-after header indicating how long to wait.")
# ---------------------------------------------------------------------------

_ANTHROPIC_TYPE_BY_STATUS = {
    429: "rate_limit_error",
    500: "api_error",
    503: "overloaded_error",
    529: "overloaded_error",
}

_ANTHROPIC_MESSAGE_BY_STATUS = {
    429: "Your account has hit a rate limit.",
    500: "An unexpected error has occurred internal to Anthropic's systems.",
    503: "The API is temporarily overloaded.",
    529: "The API is temporarily overloaded.",
}


def anthropic_error(status: int, *, retry_after_s: int | None = None) -> ErrorShape:
    """A synthetic Anthropic-shaped error for status in {429, 500, 503, 529}."""
    if status not in _ANTHROPIC_TYPE_BY_STATUS:
        raise ValueError(f"no pinned Anthropic shape for status {status}")
    body = {
        "type": "error",
        "error": {
            "type": _ANTHROPIC_TYPE_BY_STATUS[status],
            "message": _ANTHROPIC_MESSAGE_BY_STATUS[status],
        },
        "request_id": "req_chaosllm_synthetic",
    }
    headers = {}
    if status == 429:
        headers["retry-after"] = str(retry_after_s if retry_after_s is not None else 20)
    return ErrorShape(status=status, body=body, headers=headers)


def anthropic_context_overflow(*, limit: int = 200000, requested: int = 205092) -> ErrorShape:
    """Anthropic's "prompt is too long" shape (400, invalid_request_error).

    The exact "prompt is too long: X tokens > Y maximum" message pattern is
    widely observed and stable, but not quoted verbatim on the errors docs
    page, so treat the message text (not the type/status) as representative.
    """
    return ErrorShape(
        status=400,
        body={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": f"prompt is too long: {requested} tokens > {limit} maximum",
            },
            "request_id": "req_chaosllm_synthetic",
        },
        headers={},
    )
