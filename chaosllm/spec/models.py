"""Experiment spec models (DESIGN.md 4.3).

The shape deliberately mirrors Chaos Mesh / Gremlin conventions: a named
experiment, blast radius via route matching, steady-state assertions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from chaosllm.faults.models import FaultConfig


class Target(BaseModel):
    base_url: str
    endpoint: str
    payload_file: Path


class LoadConfig(BaseModel):
    concurrency: int = Field(gt=0)
    duration_s: float = Field(gt=0)
    warmup_s: float = Field(ge=0)


class SuccessRateAssertion(BaseModel):
    type: Literal["success_rate"] = "success_rate"
    min: float = Field(ge=0.0, le=1.0)


class LatencyP95Assertion(BaseModel):
    type: Literal["latency_p95_ms"] = "latency_p95_ms"
    max: float = Field(gt=0)


class ResponseContainsAssertion(BaseModel):
    type: Literal["response_contains"] = "response_contains"
    field: str
    forbid_empty: bool = False


class JsonFieldPresentAssertion(BaseModel):
    type: Literal["json_field_present"] = "json_field_present"
    field: str
    min_items: int = Field(default=1, ge=0)


Assertion = Annotated[
    SuccessRateAssertion
    | LatencyP95Assertion
    | ResponseContainsAssertion
    | JsonFieldPresentAssertion,
    Field(discriminator="type"),
]


class ExperimentSpec(BaseModel):
    name: str
    description: str = ""
    target: Target
    load: LoadConfig
    faults: list[FaultConfig] = Field(default_factory=list)
    assertions: list[Assertion] = Field(default_factory=list)
