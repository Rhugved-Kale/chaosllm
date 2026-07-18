"""Naive vs resilient /ask behavior under a faulted (respx-mocked) LLM call.

This is the core of DESIGN.md 4.6's demo story: same fault, two outcomes.
The naive path has no timeout override, no retries, no fallback, so a bad
upstream response becomes a bare 500. The resilient path retries, then falls
back to an extractive (retrieval-only) answer instead of failing.
"""

from __future__ import annotations

import httpx
import pytest
import respx

OPENAI_URL = "http://127.0.0.1:8000/openai/v1/chat/completions"


def _mock_ok(router: respx.MockRouter) -> None:
    router.route(host="test").pass_through()
    router.post(OPENAI_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "an answer"}}]})
    )


def _mock_error(router: respx.MockRouter, status: int) -> None:
    router.route(host="test").pass_through()
    router.post(OPENAI_URL).mock(return_value=httpx.Response(status, json={"error": "boom"}))


async def test_naive_path_succeeds_when_upstream_is_healthy(client: httpx.AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_ok(router)
        response = await client.post("/ask", json={"question": "what is water?"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "an answer"
    assert body["citations"]
    assert body["degraded"] is False


async def test_naive_path_propagates_upstream_error(client: httpx.AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_error(router, 500)
        response = await client.post("/ask", json={"question": "what is water?"})
    assert response.status_code == 500


async def test_resilient_path_falls_back_to_extractive_answer_on_sustained_error(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESILIENT", "true")
    with respx.mock(assert_all_called=False) as router:
        _mock_error(router, 500)
        response = await client.post("/ask", json={"question": "what is water?"})
    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert body["answer"]
    assert body["citations"]


async def test_resilient_path_succeeds_normally_when_upstream_is_healthy(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESILIENT", "true")
    with respx.mock(assert_all_called=False) as router:
        _mock_ok(router)
        response = await client.post("/ask", json={"question": "what is water?"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "an answer"
    assert body["degraded"] is False


async def test_resilient_path_survives_malformed_json_body(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """malformed_json / truncate faults corrupt the body but keep status 200;
    the resilient path must not crash trying to parse it."""
    monkeypatch.setenv("RESILIENT", "true")
    with respx.mock(assert_all_called=False) as router:
        router.route(host="test").pass_through()
        router.post(OPENAI_URL).mock(
            return_value=httpx.Response(
                200, content=b'{"choices": [{"message": {"content": "cut off'
            )
        )
        response = await client.post("/ask", json={"question": "what is water?"})
    assert response.status_code == 200
    assert response.json()["degraded"] is True


async def test_circuit_breaker_opens_after_repeated_failures(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESILIENT", "true")
    with respx.mock(assert_all_called=False) as router:
        _mock_error(router, 500)
        for _ in range(3):
            response = await client.post("/ask", json={"question": "q"})
            assert response.status_code == 200
            assert response.json()["degraded"] is True

        route = router.post(OPENAI_URL)
        calls_before = route.call_count

        # The breaker should now be open: this call must not reach the
        # (mocked) network at all.
        response = await client.post("/ask", json={"question": "q"})
        assert response.status_code == 200
        assert response.json()["degraded"] is True
        assert route.call_count == calls_before
