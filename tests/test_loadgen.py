"""run_load: concurrency-controlled load generation, periodic on_progress ticks
for live dashboard updates (DESIGN.md 4.7)."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from chaosllm.runner.loadgen import RequestResult, run_load
from chaosllm.runner.phases import Phase


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://target")


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"answer": "ok"})


async def test_on_progress_receives_growing_snapshots() -> None:
    snapshots: list[int] = []

    async def on_progress(results: list[RequestResult]) -> None:
        snapshots.append(len(results))

    async with _client(_ok) as client:
        results = await run_load(
            client=client,
            method="POST",
            url="/ask",
            payloads=[{"question": "q"}],
            concurrency=2,
            duration_s=0.3,
            phase=Phase.CHAOS,
            on_progress=on_progress,
            progress_interval_s=0.05,
        )

    assert len(results) > 0
    assert len(snapshots) >= 3
    assert snapshots == sorted(snapshots)  # non-decreasing, each tick sees more (or equal) results


async def test_no_progress_ticks_without_a_callback() -> None:
    async with _client(_ok) as client:
        results = await run_load(
            client=client,
            method="POST",
            url="/ask",
            payloads=[{"question": "q"}],
            concurrency=1,
            duration_s=0.1,
            phase=Phase.WARMUP,
        )
    assert len(results) > 0


async def test_ticker_is_cancelled_cleanly_when_load_finishes() -> None:
    """A slow callback must not leak a background task or delay completion
    past the load itself finishing."""
    calls = 0

    async def on_progress(results: list[RequestResult]) -> None:
        nonlocal calls
        calls += 1

    async with _client(_ok) as client:
        await run_load(
            client=client,
            method="POST",
            url="/ask",
            payloads=[{"question": "q"}],
            concurrency=1,
            duration_s=0.05,
            phase=Phase.RECOVERY,
            on_progress=on_progress,
            progress_interval_s=0.02,
        )
    # Completes without hanging; the exact tick count isn't the point here.


async def test_short_phase_is_not_delayed_by_a_longer_progress_interval() -> None:
    """Regression: tick_count used to be max(1, ...) + padding, so a phase
    shorter than one progress_interval_s still forced gather() to wait out
    a full interval it didn't need. A 0.05s phase with a 2s interval must
    finish in well under a second, with zero ticks (nothing to report yet).
    """
    calls = 0

    async def on_progress(results: list[RequestResult]) -> None:
        nonlocal calls
        calls += 1

    async with _client(_ok) as client:
        start = time.perf_counter()
        await run_load(
            client=client,
            method="POST",
            url="/ask",
            payloads=[{"question": "q"}],
            concurrency=1,
            duration_s=0.05,
            phase=Phase.WARMUP,
            on_progress=on_progress,
            progress_interval_s=2.0,
        )
        elapsed = time.perf_counter() - start

    assert elapsed < 1.0
    assert calls == 0
