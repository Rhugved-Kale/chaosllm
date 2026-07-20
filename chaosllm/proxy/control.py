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
import os
import re
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from chaosllm.faults.models import FaultConfig
from chaosllm.faults.pipeline import FaultPipeline
from chaosllm.metrics.events import EventBus
from chaosllm.metrics.tap import MetricsTap, fault_fire_counts_since, now_iso
from chaosllm.proxy.budget import BudgetTracker
from chaosllm.proxy.demo_trigger import DemoTrigger
from chaosllm.runner.runner import run_experiment

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
    degraded_rate: float | None = None
    completed_at: str | None = None
    fault_fire_counts: dict[str, int] = Field(default_factory=dict)
    assertions: list[AssertionStatus] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LatestRunResponse(BaseModel):
    run_id: str | None


class DemoTriggerResponse(BaseModel):
    status: Literal[
        "started", "already_running", "rate_limited", "budget_exhausted", "not_configured"
    ]
    detail: str
    retry_after_s: int | None = None


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


@router.post("/demo/trigger", response_model=DemoTriggerResponse)
async def trigger_demo_run(
    request: Request, background_tasks: BackgroundTasks
) -> DemoTriggerResponse:
    """Starts a short (~50s), real experiment against the hosted demo app on
    demand, for the dashboard's "Run a live experiment" button. Public and
    unauthenticated like every other route here (DESIGN.md 4.1), so the
    gates that matter are DemoTrigger's own rate limit and the existing
    budget cap, checked before anything is actually started.
    """
    trigger: DemoTrigger | None = request.app.state.demo_trigger
    if trigger is None:
        return DemoTriggerResponse(
            status="not_configured",
            detail="This deployment hasn't set DEMO_APP_URL, so there's no demo app to trigger.",
        )

    budget: BudgetTracker = request.app.state.budget_tracker
    if budget.is_exhausted():
        return DemoTriggerResponse(
            status="budget_exhausted",
            detail="Today's demo budget is used up. Try again after 00:00 UTC.",
        )

    decision = await trigger.try_start()
    if not decision.allowed:
        if decision.reason == "already_running":
            return DemoTriggerResponse(
                status="already_running",
                detail="A triggered run is already in progress. Watch the panel above.",
            )
        return DemoTriggerResponse(
            status="rate_limited",
            detail=f"This demo can only be triggered {trigger.max_per_hour} times per hour.",
            retry_after_s=decision.retry_after_s,
        )

    background_tasks.add_task(_run_triggered_demo, trigger)
    return DemoTriggerResponse(
        status="started",
        detail="Starting a real experiment now. Watch the panel above.",
    )


async def _run_triggered_demo(trigger: DemoTrigger) -> None:
    """Runs trigger.spec_path against trigger.demo_app_url, targeting this
    same process's own control API (self-loopback: the runner posts
    progress events and queries fault-fire counts over HTTP, and this
    process is already serving that API).

    run_experiment persists a few rows via MetricsStore's plain, synchronous
    sqlite3 calls (a handful of writes across the whole run, not per
    request, see store.py's own comment on this), which briefly shares the
    event loop with real proxy traffic each time. Acceptable for something
    rate-limited to a few runs an hour; not worth making the store async
    over.
    """
    spec_text = trigger.spec_path.read_text(encoding="utf-8")
    substituted = re.sub(
        r"base_url:\s*\S+", f"base_url: {trigger.demo_app_url}", spec_text, count=1
    )

    tmp_spec_fd, tmp_spec_name = tempfile.mkstemp(suffix=".yaml")
    tmp_spec_path = Path(tmp_spec_name)
    with os.fdopen(tmp_spec_fd, "w", encoding="utf-8") as tmp_spec_file:
        tmp_spec_file.write(substituted)

    proxy_self_url = f"http://127.0.0.1:{os.environ.get('PORT', '8000')}"

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_dir_path = Path(tmp_dir)
            await run_experiment(
                tmp_spec_path,
                proxy_url=proxy_self_url,
                db_path=tmp_dir_path / "trigger.db",
                runs_dir=tmp_dir_path / "runs",
            )
    finally:
        tmp_spec_path.unlink(missing_ok=True)
        await trigger.finish()
