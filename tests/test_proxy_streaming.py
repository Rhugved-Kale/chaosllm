"""Streaming responses (e.g. SSE) pass through unmodified."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from chaosllm.proxy.app import create_app
from chaosllm.proxy.config import ProxyConfig


async def test_streaming_response_passes_through_intact(tmp_path: Path) -> None:
    asgi_app = create_app(config=ProxyConfig(), metrics_path=tmp_path / "metrics.jsonl")
    sse_body = b'data: {"delta":"a"}\n\ndata: {"delta":"b"}\n\ndata: [DONE]\n\n'

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
                json={"model": "gpt-4o-mini", "stream": True},
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.content == sse_body
