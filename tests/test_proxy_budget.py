"""Budget enforcement wired into the proxy: 402 past cap, cost tracked from
real usage, passthrough routes are never budgeted."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import httpx
import respx

from chaosllm.proxy.app import create_app
from chaosllm.proxy.budget import BudgetTracker
from chaosllm.proxy.config import PassthroughTarget, ProxyConfig


async def test_returns_402_once_budget_exhausted(tmp_path: Path) -> None:
    budget = BudgetTracker(daily_cap_usd=0.01)
    await budget.add_cost(0.01)
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl", budget_tracker=budget)

    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        resp = await client.post(
            "/openai/v1/chat/completions", json={"model": "gpt-5.4-mini", "messages": []}
        )

    assert resp.status_code == 402
    assert resp.json()["error"]["type"] == "budget_exceeded"


async def test_no_cap_configured_never_blocks(tmp_path: Path) -> None:
    asgi_app = create_app(
        metrics_path=tmp_path / "metrics.jsonl", budget_tracker=BudgetTracker(daily_cap_usd=None)
    )

    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": []})
        )
        transport = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            resp = await client.post(
                "/openai/v1/chat/completions", json={"model": "gpt-5.4-mini", "messages": []}
            )
    assert resp.status_code == 200


async def test_real_usage_is_tracked_against_the_cap(tmp_path: Path) -> None:
    budget = BudgetTracker(daily_cap_usd=1.0)
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl", budget_tracker=budget)

    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "hi"}}],
                    "usage": {"prompt_tokens": 100_000, "completion_tokens": 100_000},
                },
            )
        )
        transport = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            resp = await client.post(
                "/openai/v1/chat/completions", json={"model": "gpt-5.4-mini", "messages": []}
            )

    assert resp.status_code == 200
    # 100k input @ $0.75/MTok + 100k output @ $4.50/MTok = $0.075 + $0.45
    assert budget.spent_usd == (100_000 * 0.75 + 100_000 * 4.50) / 1_000_000


async def test_passthrough_routes_are_never_budgeted(tmp_path: Path) -> None:
    """A vector-DB passthrough target should never be blocked by the LLM cap."""
    budget = BudgetTracker(daily_cap_usd=0.01)
    await budget.add_cost(0.01)
    config = ProxyConfig(
        passthrough={"vectordb": PassthroughTarget(base_url="http://vectordb.internal")}
    )
    asgi_app = create_app(
        config=config, metrics_path=tmp_path / "metrics.jsonl", budget_tracker=budget
    )

    with respx.mock(assert_all_called=True) as mock:
        mock.get("http://vectordb.internal/health").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        transport = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            resp = await client.get("/passthrough/vectordb/health")

    assert resp.status_code == 200


async def test_gzip_encoded_upstream_response_is_forwarded_decoded(tmp_path: Path) -> None:
    """Cost tracking buffers the response via `.aread()`, which httpx
    transparently gunzips. Forwarding the original content-encoding header
    alongside that already-decoded body would make the downstream client try
    to gunzip plain bytes and fail; this was a real bug found live against a
    hosted Anthropic deployment (gzip is routine over the real network,
    unlike respx's uncompressed-by-default mocks in the other tests here)."""
    budget = BudgetTracker(daily_cap_usd=1.0)
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl", budget_tracker=budget)
    payload = json.dumps(
        {
            "content": [{"type": "text", "text": "hi"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    ).encode()

    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                content=gzip.compress(payload),
                headers={"content-encoding": "gzip", "content-type": "application/json"},
            )
        )
        transport = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            resp = await client.post("/anthropic/v1/messages", json={"model": "claude-haiku-4-5"})

    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") is None
    assert resp.json()["content"][0]["text"] == "hi"


async def test_streaming_request_is_not_buffered_for_cost_tracking(tmp_path: Path) -> None:
    """A `stream: true` request keeps true pass-through; cost just isn't
    tracked for it (documented limitation), rather than buffering it."""
    budget = BudgetTracker(daily_cap_usd=1.0)
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl", budget_tracker=budget)
    sse_body = b'data: {"delta":"a"}\n\ndata: [DONE]\n\n'

    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, content=sse_body, headers={"content-type": "text/event-stream"}
            )
        )
        transport = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            resp = await client.post(
                "/openai/v1/chat/completions",
                json={"model": "gpt-5.4-mini", "stream": True},
            )

    assert resp.status_code == 200
    assert resp.content == sse_body
    assert budget.spent_usd == 0.0
