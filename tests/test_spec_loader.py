"""Experiment spec YAML loader: valid specs parse, invalid ones point at a line."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaosllm.spec.loader import SpecValidationError, load_experiment_spec

VALID_SPEC = """\
name: vector-db-latency-spike
description: RAG behavior when retrieval latency exceeds 200ms
target:
  base_url: http://localhost:8100
  endpoint: POST /ask
  payload_file: payloads/questions.jsonl
load:
  concurrency: 8
  duration_s: 120
  warmup_s: 15
faults:
  - id: latency
    route: /passthrough/vectordb/*
    delay_ms: 300
    jitter_ms: 100
    p: 1.0
assertions:
  - type: success_rate
    min: 0.95
  - type: latency_p95_ms
    max: 4000
"""

INVALID_SPEC = """\
name: bad-load
target:
  base_url: http://localhost:8100
  endpoint: POST /ask
  payload_file: payloads.jsonl
load:
  concurrency: "eight"
  duration_s: 120
  warmup_s: 15
"""


def test_load_valid_spec(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(VALID_SPEC, encoding="utf-8")

    spec = load_experiment_spec(spec_path)

    assert spec.name == "vector-db-latency-spike"
    assert spec.load.concurrency == 8
    assert spec.faults[0].id == "latency"
    assert spec.faults[0].delay_ms == 300  # type: ignore[union-attr]
    assert spec.assertions[0].type == "success_rate"
    assert spec.assertions[0].min == 0.95  # type: ignore[union-attr]


def test_invalid_spec_points_at_the_offending_line(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(INVALID_SPEC, encoding="utf-8")

    expected_line = next(
        i + 1 for i, line in enumerate(INVALID_SPEC.splitlines()) if "concurrency" in line
    )

    with pytest.raises(SpecValidationError) as exc_info:
        load_experiment_spec(spec_path)

    error = exc_info.value
    assert error.errors
    line, message = error.errors[0]
    assert line == expected_line
    assert str(spec_path) in str(error)
    assert str(expected_line) in str(error)
