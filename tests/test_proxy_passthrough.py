"""Generic /passthrough/{id}/* route: config-driven forwarding, 404 on unknown id."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from chaosllm.proxy.app import create_app
from chaosllm.proxy.config import PassthroughTarget, ProxyConfig


async def test_unknown_passthrough_target_returns_404(tmp_path: Path) -> None:
    asgi_app = create_app(config=ProxyConfig(), metrics_path=tmp_path / "metrics.jsonl")

    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        resp = await client.get("/passthrough/vectordb/health")

    assert resp.status_code == 404


async def test_known_passthrough_target_forwards(tmp_path: Path) -> None:
    config = ProxyConfig(
        passthrough={"vectordb": PassthroughTarget(base_url="http://vectordb.internal")}
    )
    asgi_app = create_app(config=config, metrics_path=tmp_path / "metrics.jsonl")

    with respx.mock(assert_all_called=True) as mock:
        mock.get("http://vectordb.internal/health").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        transport = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            resp = await client.get("/passthrough/vectordb/health")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
