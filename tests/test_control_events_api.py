"""Control API: POST a progress event, GET it back over SSE, GET the latest
run_id for dashboard auto-connect."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from chaosllm.proxy.app import create_app


async def test_latest_run_id_is_none_before_any_events(tmp_path: Path) -> None:
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl")
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        resp = await client.get("/control/runs/latest")
        assert resp.status_code == 200
        assert resp.json() == {"run_id": None}


async def test_post_event_then_get_latest_run_id(tmp_path: Path) -> None:
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl")
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        post_resp = await client.post(
            "/control/runs/my-run-1/events",
            json={"type": "progress", "phase": "chaos", "total_count": 5, "success_count": 4},
        )
        assert post_resp.status_code == 200

        latest = await client.get("/control/runs/latest")
        assert latest.json() == {"run_id": "my-run-1"}


async def test_sse_stream_delivers_posted_events_and_closes_on_completion(tmp_path: Path) -> None:
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl")
    transport = httpx.ASGITransport(app=asgi_app)

    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        received: list[dict[str, object]] = []

        async def consume() -> None:
            async with client.stream("GET", "/control/runs/my-run-2/events") as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        received.append(json.loads(line[len("data: ") :]))
                        if received[-1].get("type") == "run_complete":
                            return

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.05)  # let the subscriber register before publishing

        await client.post(
            "/control/runs/my-run-2/events",
            json={"type": "progress", "phase": "warmup", "total_count": 1, "success_count": 1},
        )
        await client.post("/control/runs/my-run-2/events", json={"type": "run_complete"})

        await asyncio.wait_for(consumer, timeout=2.0)

    assert received[0]["phase"] == "warmup"
    assert received[-1]["type"] == "run_complete"


async def test_subscribing_after_run_complete_still_delivers_it(tmp_path: Path) -> None:
    """A dashboard opening /control/runs/{id}/events after that run already
    finished (e.g. the tab was opened between runs) must see the completed
    state over the wire, not an SSE connection that never sends anything."""
    asgi_app = create_app(metrics_path=tmp_path / "metrics.jsonl")
    transport = httpx.ASGITransport(app=asgi_app)

    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        await client.post(
            "/control/runs/my-run-3/events",
            json={"type": "progress", "phase": "chaos", "total_count": 1, "success_count": 1},
        )
        await client.post("/control/runs/my-run-3/events", json={"type": "run_complete"})

        received: list[dict[str, object]] = []
        async with client.stream("GET", "/control/runs/my-run-3/events") as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    received.append(json.loads(line[len("data: ") :]))
                    if received[-1].get("type") == "run_complete":
                        break

    assert len(received) == 1
    assert received[0]["type"] == "run_complete"
