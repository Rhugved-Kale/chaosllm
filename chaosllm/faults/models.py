"""Pydantic parameter models for the eight v0.1 fault types (DESIGN.md 4.2).

Each fault carries its own `route` glob (fnmatch-style, matched against the
request path, e.g. `/passthrough/vectordb/*`) and its own probability `p`,
per DESIGN.md 4.1: "Each fault decides independently (probability per fault)
whether to fire." `rate_limit_burst` has no `p`; it is deterministic state,
not a coin flip.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class FaultBase(BaseModel):
    route: str = "*"


class LatencyFault(FaultBase):
    id: Literal["latency"] = "latency"
    delay_ms: int = Field(ge=0)
    jitter_ms: int = Field(default=0, ge=0)
    p: Probability = 1.0


class ErrorFault(FaultBase):
    id: Literal["error"] = "error"
    status: Literal[429, 500, 503]
    body: dict[str, object] | None = None
    p: Probability = 1.0


class TimeoutFault(FaultBase):
    id: Literal["timeout"] = "timeout"
    hold_ms: int = Field(ge=0)
    p: Probability = 1.0


class TruncateFault(FaultBase):
    id: Literal["truncate"] = "truncate"
    keep_fraction: float = Field(gt=0.0, le=1.0)
    p: Probability = 1.0


class MalformedJsonFault(FaultBase):
    id: Literal["malformed_json"] = "malformed_json"
    mode: Literal["drop_closing_brace", "mangle_key"] = "drop_closing_brace"
    p: Probability = 1.0


class ContextOverflowFault(FaultBase):
    id: Literal["context_overflow"] = "context_overflow"
    p: Probability = 1.0


class ModelDowngradeFault(FaultBase):
    id: Literal["model_downgrade"] = "model_downgrade"
    to_model: str
    p: Probability = 1.0


class RateLimitBurstFault(FaultBase):
    id: Literal["rate_limit_burst"] = "rate_limit_burst"
    limit: int = Field(gt=0)
    window_s: float = Field(gt=0.0)


FaultConfig = Annotated[
    LatencyFault
    | ErrorFault
    | TimeoutFault
    | TruncateFault
    | MalformedJsonFault
    | ContextOverflowFault
    | ModelDowngradeFault
    | RateLimitBurstFault,
    Field(discriminator="id"),
]
