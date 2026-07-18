"""Control API: runtime fault configuration (DESIGN.md 4.1).

"Fault state is set at runtime by the runner via a control API ... so one
long-lived proxy serves many experiments." The Phase 3 runner will call
POST before the chaos phase and DELETE before the recovery phase.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from chaosllm.faults.models import FaultConfig
from chaosllm.faults.pipeline import FaultPipeline

router = APIRouter(prefix="/control", tags=["control"])


class SetFaultsRequest(BaseModel):
    faults: list[FaultConfig]


class FaultsResponse(BaseModel):
    faults: list[FaultConfig]


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
