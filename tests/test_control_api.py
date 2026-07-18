"""Control API: turn a fault on via POST, watch it fire, turn it off via DELETE."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from chaosllm.proxy.app import create_app
from chaosllm.proxy.config import ProxyConfig


async def test_post_faults_then_delete_restores_passthrough(tmp_path: Path) -> None:
    asgi_app = create_app(config=ProxyConfig(), metrics_path=tmp_path / "metrics.jsonl")
    transport = httpx.ASGITransport(app=asgi_app)

    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        set_resp = await client.post(
            "/control/faults",
            json={"faults": [{"id": "error", "status": 429, "route": "/openai/*", "p": 1.0}]},
        )
        assert set_resp.status_code == 200
        assert len(set_resp.json()["faults"]) == 1

        with respx.mock(assert_all_called=False) as mock:
            route = mock.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json={"ok": True})
            )
            faulted_resp = await client.post(
                "/openai/v1/chat/completions", json={"model": "gpt-4o-mini"}
            )
            assert faulted_resp.status_code == 429
            assert faulted_resp.json()["error"]["code"] == "rate_limit_exceeded"
            assert route.call_count == 0

        clear_resp = await client.delete("/control/faults")
        assert clear_resp.status_code == 200
        assert clear_resp.json()["faults"] == []

        with respx.mock(assert_all_called=True) as mock:
            mock.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json={"ok": True})
            )
            clean_resp = await client.post(
                "/openai/v1/chat/completions", json={"model": "gpt-4o-mini"}
            )
            assert clean_resp.status_code == 200
            assert clean_resp.json() == {"ok": True}
