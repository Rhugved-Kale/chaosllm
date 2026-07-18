"""Pinned provider error shapes match the envelope each SDK actually parses."""

from __future__ import annotations

import pytest

from chaosllm.faults import provider_shapes


@pytest.mark.parametrize("status", [429, 500, 503])
def test_openai_error_envelope(status: int) -> None:
    shape = provider_shapes.openai_error(status)
    assert shape.status == status
    assert set(shape.body.keys()) == {"error"}
    error = shape.body["error"]
    assert set(error.keys()) == {"message", "type", "param", "code"}
    assert isinstance(error["message"], str) and error["message"]


def test_openai_rate_limit_has_ratelimit_headers_not_retry_after() -> None:
    shape = provider_shapes.openai_error(429)
    assert "x-ratelimit-reset-requests" in shape.headers
    assert "retry-after" not in shape.headers
    assert shape.body["error"]["code"] == "rate_limit_exceeded"


def test_openai_context_length_exceeded() -> None:
    shape = provider_shapes.openai_context_length_exceeded()
    assert shape.status == 400
    assert shape.body["error"]["code"] == "context_length_exceeded"
    assert shape.body["error"]["type"] == "invalid_request_error"
    assert shape.body["error"]["param"] == "messages"


@pytest.mark.parametrize("status", [429, 500, 503, 529])
def test_anthropic_error_envelope(status: int) -> None:
    shape = provider_shapes.anthropic_error(status)
    assert shape.status == status
    assert shape.body["type"] == "error"
    assert set(shape.body["error"].keys()) == {"type", "message"}
    assert "request_id" in shape.body


def test_anthropic_rate_limit_has_retry_after_header() -> None:
    shape = provider_shapes.anthropic_error(429)
    assert shape.headers["retry-after"] == "20"
    assert shape.body["error"]["type"] == "rate_limit_error"


def test_anthropic_context_overflow() -> None:
    shape = provider_shapes.anthropic_context_overflow()
    assert shape.status == 400
    assert shape.body["error"]["type"] == "invalid_request_error"
    assert "too long" in shape.body["error"]["message"]


def test_unpinned_status_raises() -> None:
    with pytest.raises(ValueError, match="no pinned"):
        provider_shapes.openai_error(418)
    with pytest.raises(ValueError, match="no pinned"):
        provider_shapes.anthropic_error(418)
