"""Calls to the LLM provider, through the chaosllm proxy.

Two code paths behind the RESILIENT flag (DESIGN.md 4.6):
  - naive: no explicit timeout override, no retries, no fallback. A
    blackholed proxy call hangs the naive path exactly like it would in a
    real, unguarded production app.
  - resilient: an explicit httpx timeout, tenacity retries with jitter on
    retryable failures, and a circuit breaker so a sustained outage stops
    hammering a dead upstream instead of retrying it into the ground.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_random_exponential

from demo.circuit_breaker import CircuitBreaker, CircuitOpenError

RESILIENT_TIMEOUT_S = 5.0
RESILIENT_MAX_ATTEMPTS = 3

_breaker = CircuitBreaker(failure_threshold=3, reset_after_s=5.0)


class LLMUnavailableError(Exception):
    pass


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException | httpx.ConnectError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, LLMUnavailableError):
        # Malformed/truncated bodies (the truncate and malformed_json
        # faults) surface here too: worth one retry, same as a bad status.
        return True
    return False


def _chat_payload(question: str, context: str) -> dict[str, Any]:
    return {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": f"Answer using only this context:\n{context}"},
            {"role": "user", "content": question},
        ],
    }


def _extract_text(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMUnavailableError("malformed LLM response: no choices")
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text:
        raise LLMUnavailableError("malformed LLM response: empty content")
    return text


async def naive_ask_llm(client: httpx.AsyncClient, question: str, context: str) -> str:
    """No timeout override, no retries, no fallback: mirrors an unguarded prod app."""
    response = await client.post(
        "/openai/v1/chat/completions", json=_chat_payload(question, context), timeout=None
    )
    response.raise_for_status()
    return _extract_text(response.json())


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(RESILIENT_MAX_ATTEMPTS),
    wait=wait_random_exponential(multiplier=0.1, max=1.0),
    reraise=True,
)
async def _resilient_call(client: httpx.AsyncClient, question: str, context: str) -> str:
    response = await client.post(
        "/openai/v1/chat/completions",
        json=_chat_payload(question, context),
        timeout=RESILIENT_TIMEOUT_S,
    )
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError as exc:
        raise LLMUnavailableError(f"malformed LLM response: {exc}") from exc
    return _extract_text(body)


async def resilient_ask_llm(client: httpx.AsyncClient, question: str, context: str) -> str:
    """Timeout + retry-with-jitter + circuit breaker.

    Raises LLMUnavailableError on final failure so the caller can fall back
    to an extractive (retrieval-only) answer instead of failing the request.
    """
    try:
        _breaker.before_call()
        text = await _resilient_call(client, question, context)
    except CircuitOpenError as exc:
        raise LLMUnavailableError("circuit open") from exc
    except (httpx.HTTPError, LLMUnavailableError) as exc:
        _breaker.record_failure()
        raise LLMUnavailableError(str(exc)) from exc
    else:
        _breaker.record_success()
        return text
