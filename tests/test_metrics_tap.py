"""MetricsTap writes one well-formed JSON line per record, in order, and
fault_fire_counts_since() reads them back filtered to a time window."""

from __future__ import annotations

import json
from pathlib import Path

from chaosllm.metrics.tap import MetricsTap, RequestRecord, fault_fire_counts_since


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
            total_ms=12.5,
            upstream_ms=12.5,
            injected_delay_ms=0.0,
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
            total_ms=3.1,
            upstream_ms=3.1,
            injected_delay_ms=0.0,
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


async def test_record_captures_injected_delay_separately_from_upstream(tmp_path: Path) -> None:
    """The bug this schema exists to prevent: a request that took 2.8s end to
    end (2s injected + 0.8s upstream) must not show up as ~0.8s in the log.
    """
    tap = MetricsTap(tmp_path / "metrics.jsonl")
    await tap.record(
        RequestRecord(
            request_id="r1",
            timestamp="2026-01-01T00:00:00+00:00",
            method="POST",
            route="/anthropic",
            upstream="https://api.anthropic.com/v1/messages",
            status=200,
            total_ms=2840.0,
            upstream_ms=773.0,
            injected_delay_ms=2000.0,
            faults_fired=["latency"],
        )
    )

    record = json.loads(tap.path.read_text(encoding="utf-8").strip())
    assert record["total_ms"] == 2840.0
    assert record["upstream_ms"] == 773.0
    assert record["injected_delay_ms"] == 2000.0
    assert record["total_ms"] >= record["upstream_ms"] + record["injected_delay_ms"]


def test_fault_fire_counts_since_filters_by_window(tmp_path: Path) -> None:
    path = tmp_path / "metrics.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"timestamp": "2026-01-01T00:00:00+00:00", "faults_fired": ["latency"]},
                {"timestamp": "2026-01-01T00:00:05+00:00", "faults_fired": ["latency", "error"]},
                {"timestamp": "2026-01-01T00:00:10+00:00", "faults_fired": ["error"]},
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    counts = fault_fire_counts_since(
        path, since="2026-01-01T00:00:01+00:00", until="2026-01-01T00:00:09+00:00"
    )
    assert counts == {"latency": 1, "error": 1}


def test_fault_fire_counts_since_missing_file_returns_empty(tmp_path: Path) -> None:
    counts = fault_fire_counts_since(
        tmp_path / "does-not-exist.jsonl", since="2026-01-01T00:00:00+00:00", until="now"
    )
    assert counts == {}
