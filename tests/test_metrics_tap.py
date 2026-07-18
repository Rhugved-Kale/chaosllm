"""MetricsTap writes one well-formed JSON line per record, in order."""

from __future__ import annotations

import json
from pathlib import Path

from chaosllm.metrics.tap import MetricsTap, RequestRecord


async def test_record_appends_json_lines(tmp_path: Path) -> None:
    tap = MetricsTap(tmp_path / "nested" / "metrics.jsonl")

    await tap.record(
        RequestRecord(
            request_id="r1",
            timestamp="2026-01-01T00:00:00+00:00",
            method="POST",
            route="/openai",
            upstream="https://api.openai.com/v1/chat/completions",
            status=200,
            latency_ms=12.5,
        )
    )
    await tap.record(
        RequestRecord(
            request_id="r2",
            timestamp="2026-01-01T00:00:01+00:00",
            method="GET",
            route="/passthrough/vectordb",
            upstream="http://vectordb.internal/health",
            status=404,
            latency_ms=3.1,
        )
    )

    lines = tap.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    first, second = (json.loads(line) for line in lines)
    assert first["request_id"] == "r1"
    assert first["status"] == 200
    assert first["faults_fired"] == []
    assert second["request_id"] == "r2"
    assert second["route"] == "/passthrough/vectordb"
