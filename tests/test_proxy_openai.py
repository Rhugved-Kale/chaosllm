"""Forwarding, header preservation, and metrics logging on /openai/*."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx

from chaosllm.proxy.app import create_app
from chaosllm.proxy.config import ProxyConfig


async def test_openai_forwards_body_and_preserves_headers(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    asgi_app = create_app(config=ProxyConfig(), metrics_path=metrics_path)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"id": "chatcmpl-1", "choices": []},
                headers={"x-request-id": "upstream-123"},
            )
        )

        transport = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            resp = await client.post(
                "/openai/v1/chat/completions",
                headers={"authorization": "Bearer sk-test"},
                json={"model": "gpt-4o-mini", "messages": []},
            )

        assert resp.status_code == 200
        assert resp.json() == {"id": "chatcmpl-1", "choices": []}
        assert resp.headers["x-request-id"] == "upstream-123"
        assert "x-chaosllm-request-id" in resp.headers

        sent_request = route.calls[0].request
        assert sent_request.headers["authorization"] == "Bearer sk-test"
        assert json.loads(sent_request.content) == {"model": "gpt-4o-mini", "messages": []}

    lines = metrics_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["route"] == "/openai"
    assert record["method"] == "POST"
    assert record["status"] == 200
    assert record["upstream"] == "https://api.openai.com/v1/chat/completions"
