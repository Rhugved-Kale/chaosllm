"""POST /control/demo/trigger wired into the proxy: the gating logic (not
configured, budget exhausted, rate limited, already running, started).

run_experiment itself is stubbed out here: its actual mechanics (phases,
faults, assertions) are already covered end to end in test_runner_e2e.py,
and FastAPI's BackgroundTasks run to completion before an ASGITransport
request returns, so a real experiment would make every test in this file
as slow as a real run.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

import chaosllm.proxy.control as control
from chaosllm.proxy.app import create_app
from chaosllm.proxy.budget import BudgetTracker
from chaosllm.proxy.demo_trigger import DemoTrigger


async def _fake_run_experiment(*args: object, **kwargs: object) -> None:
    return None


async def test_not_configured_without_demo_app_url(tmp_path: Path) -> None:
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl", demo_trigger=None)
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        resp = await client.post("/control/demo/trigger")
    assert resp.json()["status"] == "not_configured"


async def test_refuses_when_budget_already_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(control, "run_experiment", _fake_run_experiment)
    budget = BudgetTracker(daily_cap_usd=0.01)
    await budget.add_cost(0.01)
    trigger = DemoTrigger(demo_app_url="http://demo.internal", max_per_hour=10)
    asgi_app = create_app(
        metrics_path=tmp_path / "metrics.jsonl", budget_tracker=budget, demo_trigger=trigger
    )
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        resp = await client.post("/control/demo/trigger")
    assert resp.json()["status"] == "budget_exhausted"


async def test_starts_then_rate_limits_after_the_hourly_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(control, "run_experiment", _fake_run_experiment)
    trigger = DemoTrigger(demo_app_url="http://demo.internal", max_per_hour=1)
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl", demo_trigger=trigger)
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        first = await client.post("/control/demo/trigger")
        second = await client.post("/control/demo/trigger")

    assert first.json()["status"] == "started"
    assert second.json()["status"] == "rate_limited"
    assert second.json()["retry_after_s"] > 0


async def test_refuses_overlapping_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_run_experiment(*args: object, **kwargs: object) -> None:
        started.set()
        await release.wait()

    monkeypatch.setattr(control, "run_experiment", _slow_run_experiment)
    trigger = DemoTrigger(demo_app_url="http://demo.internal", max_per_hour=10)
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl", demo_trigger=trigger)
    transport = httpx.ASGITransport(app=asgi_app)

    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        task = asyncio.create_task(client.post("/control/demo/trigger"))
        await asyncio.wait_for(started.wait(), timeout=2.0)

        overlapping = await client.post("/control/demo/trigger")
        assert overlapping.json()["status"] == "already_running"

        release.set()
        first = await task
        assert first.json()["status"] == "started"
