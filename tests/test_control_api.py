"""Control API: turn a fault on via POST, watch it fire, turn it off via DELETE."""

from __future__ import annotations

from datetime import UTC, datetime
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


async def test_metrics_summary_reflects_faults_fired_via_http(tmp_path: Path) -> None:
    """The bug this endpoint exists to fix: a caller (the runner) must be
    able to get fault-fire counts over HTTP, not by assuming file-path
    access to the proxy's own metrics.jsonl.
    """
    asgi_app = create_app(config=ProxyConfig(), metrics_path=tmp_path / "metrics.jsonl")
    transport = httpx.ASGITransport(app=asgi_app)

    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        empty = await client.get(
            "/control/metrics/summary",
            params={"since": "2020-01-01T00:00:00+00:00", "until": "2020-01-01T00:00:01+00:00"},
        )
        assert empty.status_code == 200
        assert empty.json()["fault_fire_counts"] == {}

        await client.post(
            "/control/faults",
            json={"faults": [{"id": "error", "status": 500, "route": "/openai/*", "p": 1.0}]},
        )

        # The error fault (p=1.0) short-circuits before ever calling
        # upstream, so no respx mock is needed here at all.
        since = datetime.now(UTC).isoformat()
        for _ in range(3):
            await client.post("/openai/v1/chat/completions", json={"model": "gpt-4o-mini"})
        until = datetime.now(UTC).isoformat()

        summary_resp = await client.get(
            "/control/metrics/summary", params={"since": since, "until": until}
        )
        assert summary_resp.status_code == 200
        assert summary_resp.json()["fault_fire_counts"] == {"error": 3}
