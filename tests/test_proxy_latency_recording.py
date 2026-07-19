"""The metrics tap must record a latency fault's injected delay as part of
total_ms, not silently drop it (the bug: `start = time.perf_counter()` used
to be set *after* the injected-delay sleep, so a request that took 2.8s end
to end could log ~0.8s, since only the post-sleep upstream call was timed).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx

from chaosllm.faults.models import ErrorFault, LatencyFault
from chaosllm.faults.pipeline import FaultPipeline
from chaosllm.proxy.app import create_app


async def test_total_ms_includes_injected_latency_delay(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    pipeline = FaultPipeline()
    pipeline.set_active_faults([LatencyFault(delay_ms=200, jitter_ms=0, route="/openai/*", p=1.0)])
    asgi_app = create_app(metrics_path=metrics_path, fault_pipeline=pipeline)

    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": []})
        )
        transport = httpx.ASGITransport(app=asgi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
            resp = await client.post(
                "/openai/v1/chat/completions", json={"model": "gpt-4o-mini", "messages": []}
            )
        assert resp.status_code == 200

    record = json.loads(metrics_path.read_text(encoding="utf-8").strip())
    assert record["injected_delay_ms"] == 200.0
    assert record["upstream_ms"] is not None
    # The regression this guards against: total_ms silently equal to just
    # the upstream call, with the 200ms injected delay nowhere in the number.
    assert record["total_ms"] >= record["injected_delay_ms"] + record["upstream_ms"] - 5.0
    assert record["total_ms"] > record["upstream_ms"] + 100


async def test_total_ms_for_short_circuited_error_fault_includes_delay(tmp_path: Path) -> None:
    """latency + error composing: the synthetic error still reflects the delay."""
    metrics_path = tmp_path / "metrics.jsonl"
    pipeline = FaultPipeline()
    pipeline.set_active_faults(
        [
            LatencyFault(delay_ms=150, jitter_ms=0, route="/openai/*", p=1.0),
            ErrorFault(status=500, route="/openai/*", p=1.0),
        ]
    )
    asgi_app = create_app(metrics_path=metrics_path, fault_pipeline=pipeline)

    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        resp = await client.post(
            "/openai/v1/chat/completions", json={"model": "gpt-4o-mini", "messages": []}
        )
    assert resp.status_code == 500

    record = json.loads(metrics_path.read_text(encoding="utf-8").strip())
    assert record["upstream_ms"] is None
    assert record["injected_delay_ms"] == 150.0
    assert record["total_ms"] >= 150.0
