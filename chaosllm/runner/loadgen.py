"""Concurrency-controlled async load generator.

Drives requests at the target app, not the proxy (DESIGN.md 4.4: "Runner
drives load at the target app, not the proxy. The proxy only sees the
provider-bound traffic that the target app generates"), cycling through a
payload file for the configured duration and concurrency.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from chaosllm.metrics.tap import now_iso
from chaosllm.runner.phases import Phase

DEFAULT_REQUEST_TIMEOUT_S = 10.0


@dataclass
class RequestResult:
    phase: Phase
    timestamp: str
    status: int | None
    latency_ms: float
    success: bool
    error_kind: str | None
    response_json: dict[str, Any] | None
    degraded: bool = False


def load_payloads(payload_file: Path) -> list[dict[str, Any]]:
    payloads = [
        json.loads(line)
        for line in payload_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not payloads:
        raise ValueError(f"payload file {payload_file} has no payloads")
    return payloads


async def run_load(
    *,
    client: httpx.AsyncClient,
    method: str,
    url: str,
    payloads: list[dict[str, Any]],
    concurrency: int,
    duration_s: float,
    phase: Phase,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> list[RequestResult]:
    """Run `concurrency` workers cycling through `payloads` until `duration_s` elapses."""
    if duration_s <= 0:
        return []

    results: list[RequestResult] = []
    results_lock = asyncio.Lock()
    deadline = time.monotonic() + duration_s
    payload_cycle = itertools.cycle(payloads)

    async def worker() -> None:
        while time.monotonic() < deadline:
            payload = next(payload_cycle)
            result = await _send_one(client, method, url, payload, phase, request_timeout_s)
            async with results_lock:
                results.append(result)

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return results


async def _send_one(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    payload: dict[str, Any],
    phase: Phase,
    request_timeout_s: float,
) -> RequestResult:
    start = time.perf_counter()
    try:
        response = await client.request(method, url, json=payload, timeout=request_timeout_s)
    except httpx.TimeoutException:
        return RequestResult(
            phase=phase,
            timestamp=now_iso(),
            status=None,
            latency_ms=(time.perf_counter() - start) * 1000,
            success=False,
            error_kind="timeout",
            response_json=None,
        )
    except httpx.HTTPError:
        return RequestResult(
            phase=phase,
            timestamp=now_iso(),
            status=None,
            latency_ms=(time.perf_counter() - start) * 1000,
            success=False,
            error_kind="connection_error",
            response_json=None,
        )

    latency_ms = (time.perf_counter() - start) * 1000
    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code >= 400:
        return RequestResult(
            phase=phase,
            timestamp=now_iso(),
            status=response.status_code,
            latency_ms=latency_ms,
            success=False,
            error_kind=f"http_{response.status_code}",
            response_json=body,
        )

    degraded = isinstance(body, dict) and body.get("degraded") is True
    return RequestResult(
        phase=phase,
        timestamp=now_iso(),
        status=response.status_code,
        latency_ms=latency_ms,
        success=True,
        error_kind=None,
        response_json=body,
        degraded=degraded,
    )
