"""Control API: runtime fault configuration (DESIGN.md 4.1).

"Fault state is set at runtime by the runner via a control API ... so one
long-lived proxy serves many experiments." The Phase 3 runner will call
POST before the chaos phase and DELETE before the recovery phase.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from chaosllm.faults.models import FaultConfig
from chaosllm.faults.pipeline import FaultPipeline
from chaosllm.metrics.tap import MetricsTap, fault_fire_counts_since, now_iso

router = APIRouter(prefix="/control", tags=["control"])


class SetFaultsRequest(BaseModel):
    faults: list[FaultConfig]


class FaultsResponse(BaseModel):
    faults: list[FaultConfig]


class MetricsSummaryResponse(BaseModel):
    fault_fire_counts: dict[str, int]


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
