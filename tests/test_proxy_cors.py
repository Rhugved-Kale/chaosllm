"""CORS on the control API: the dashboard (a separate origin) must be able
to call it from browser JS (DESIGN.md 4.7)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from chaosllm.proxy.app import create_app


async def test_control_api_allows_cross_origin_by_default(tmp_path: Path) -> None:
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl")
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        resp = await client.get("/control/runs/latest", headers={"origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"


async def test_dashboard_origin_env_var_restricts_cors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://chaosllm-dashboard.example")
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl")
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        resp = await client.get(
            "/control/runs/latest", headers={"origin": "https://chaosllm-dashboard.example"}
        )
    assert resp.headers["access-control-allow-origin"] == "https://chaosllm-dashboard.example"
