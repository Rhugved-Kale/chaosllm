"""Forwarding on /anthropic/*, mirroring the /openai/* behavior."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from chaosllm.proxy.app import create_app
from chaosllm.proxy.config import ProxyConfig


async def test_anthropic_forwards_body_and_preserves_headers(tmp_path: Path) -> None:
    asgi_app = create_app(config=ProxyConfig(), metrics_path=tmp_path / "metrics.jsonl")

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json={"id": "msg_1", "content": []})
        )

        transport = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            resp = await client.post(
                "/anthropic/v1/messages",
                headers={"x-api-key": "sk-ant-test", "anthropic-version": "2023-06-01"},
                json={"model": "claude-haiku-4-5", "max_tokens": 16, "messages": []},
            )

        assert resp.status_code == 200
        assert resp.json() == {"id": "msg_1", "content": []}

        sent_request = route.calls[0].request
        assert sent_request.headers["x-api-key"] == "sk-ant-test"
        assert sent_request.headers["anthropic-version"] == "2023-06-01"
