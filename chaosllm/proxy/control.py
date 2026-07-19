"""Control API: runtime fault configuration (DESIGN.md 4.1) and live run
progress for the dashboard (DESIGN.md 4.7).

"Fault state is set at runtime by the runner via a control API ... so one
long-lived proxy serves many experiments." The runner calls POST before the
chaos phase and DELETE before the recovery phase, and pushes progress
snapshots to POST /runs/{id}/events as it drives an experiment; the
dashboard subscribes to the same run_id via GET /runs/{id}/events (SSE).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from chaosllm.faults.models import FaultConfig
from chaosllm.faults.pipeline import FaultPipeline
from chaosllm.metrics.events import EventBus
from chaosllm.metrics.tap import MetricsTap, fault_fire_counts_since, now_iso

router = APIRouter(prefix="/control", tags=["control"])


class SetFaultsRequest(BaseModel):
    faults: list[FaultConfig]


class FaultsResponse(BaseModel):
    faults: list[FaultConfig]


class MetricsSummaryResponse(BaseModel):
    fault_fire_counts: dict[str, int]


class AssertionStatus(BaseModel):
    type: str
    passed: bool
    detail: str = ""


class RunEventIn(BaseModel):
    type: Literal["progress", "run_complete"]
    phase: str | None = None
    total_count: int = 0
    success_count: int = 0
    latency_p95_ms: float | None = None
    fault_fire_counts: dict[str, int] = Field(default_factory=dict)
    assertions: list[AssertionStatus] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LatestRunResponse(BaseModel):
    run_id: str | None


@router.post("/faults", response_model=FaultsResponse)
async def set_faults(body: SetFaultsRequest, request: Request) -> FaultsResponse:
    """Replace the active fault set."""
    pipeline: FaultPipeline = request.app.state.fault_pipeline
    pipeline.set_active_faults(list(body.faults))
    return FaultsResponse(faults=pipeline.active_faults)


@router.delete("/faults", response_model=FaultsResponse)
async def clear_faults(request: Request) -> FaultsResponse:
    """Turn all faults off."""
    pipeline: FaultPipeline = request.app.state.fault_pipeline
    pipeline.clear()
    return FaultsResponse(faults=pipeline.active_faults)


@router.get("/metrics/summary", response_model=MetricsSummaryResponse)
async def metrics_summary(
    request: Request,
    since: str = Query(..., description="ISO 8601 start timestamp, inclusive."),
    until: str | None = Query(
        None, description="ISO 8601 end timestamp, inclusive. Defaults to now."
    ),
) -> MetricsSummaryResponse:
    """Fault-fire counts for a time window, read from the proxy's own metrics.

    Exists so a caller (the runner) gets this over HTTP instead of assuming
    file-path access to metrics.jsonl: that assumption breaks the moment the
    proxy runs in a different process or container than the caller.
    """
    metrics: MetricsTap = request.app.state.metrics
    counts = fault_fire_counts_since(metrics.path, since=since, until=until or now_iso())
    return MetricsSummaryResponse(fault_fire_counts=counts)


@router.post("/runs/{run_id}/events")
async def post_run_event(run_id: str, event: RunEventIn, request: Request) -> dict[str, str]:
    """The runner calls this periodically while driving an experiment."""
    bus: EventBus = request.app.state.event_bus
    bus.publish(run_id, event.model_dump())
    return {"status": "ok"}


@router.get("/runs/latest", response_model=LatestRunResponse)
async def get_latest_run(request: Request) -> LatestRunResponse:
    """The most recent run_id the proxy has seen an event for, if any.

    Lets the dashboard auto-connect without the user having to know or type
    a run_id.
    """
    bus: EventBus = request.app.state.event_bus
    return LatestRunResponse(run_id=bus.latest_run_id)


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str, request: Request) -> StreamingResponse:
    """Server-sent events: one `data: {json}\\n\\n` line per progress update,
    stream ends after a run_complete event."""
    bus: EventBus = request.app.state.event_bus

    async def event_stream() -> AsyncIterator[str]:
        async for event in bus.subscribe(run_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
