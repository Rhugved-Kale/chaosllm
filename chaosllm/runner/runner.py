"""Experiment orchestration: warmup -> chaos -> recovery against the target
app, toggling the proxy's fault set via the control API, then summarizing
and persisting results (DESIGN.md 4.4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from chaosllm.metrics.store import AssertionResult, MetricsStore, PhaseSummary
from chaosllm.metrics.tap import now_iso
from chaosllm.runner.loadgen import (
    DEFAULT_REQUEST_TIMEOUT_S,
    RequestResult,
    load_payloads,
    run_load,
)
from chaosllm.runner.phases import Phase
from chaosllm.spec.loader import load_experiment_spec
from chaosllm.spec.models import (
    ExperimentSpec,
    JsonFieldPresentAssertion,
    LatencyP95Assertion,
    ResponseContainsAssertion,
    SuccessRateAssertion,
)

ZERO_CHAOS_FAULTS_WARNING = (
    "chaos phase fired zero faults even though {n} fault(s) were configured; "
    "the fault route likely never saw any traffic (check target.endpoint and "
    "each fault's route glob against what the target app actually calls "
    "through the proxy). This run is not a valid chaos signal."
)


@dataclass
class RunSummary:
    run_id: str
    spec: ExperimentSpec
    phase_summaries: list[PhaseSummary]
    assertion_results: list[AssertionResult]
    fault_fire_counts: dict[str, int]
    warnings: list[str]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * pct
    lower = int(k)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (k - lower)


def summarize_phase(
    phase: Phase, results: list[RequestResult], fault_fire_counts: dict[str, int]
) -> PhaseSummary:
    total = len(results)
    success = sum(1 for r in results if r.success)
    latencies = sorted(r.latency_ms for r in results)
    taxonomy: dict[str, int] = {}
    for r in results:
        if r.error_kind:
            taxonomy[r.error_kind] = taxonomy.get(r.error_kind, 0) + 1
    return PhaseSummary(
        phase=phase.value,
        total_count=total,
        success_count=success,
        error_count=total - success,
        latency_p50_ms=_percentile(latencies, 0.50) if latencies else None,
        latency_p95_ms=_percentile(latencies, 0.95) if latencies else None,
        latency_p99_ms=_percentile(latencies, 0.99) if latencies else None,
        error_taxonomy=taxonomy,
        fault_fire_counts=fault_fire_counts,
    )


def evaluate_assertions(
    assertions: list[Any], chaos_results: list[RequestResult]
) -> list[AssertionResult]:
    """Assertions run against the chaos phase: that's the resilience question.

    response_contains / json_field_present pass only if every *successful*
    response satisfies the structural check; a single malformed answer is a
    real finding, not noise to average away.
    """
    total = len(chaos_results)
    successes = [r for r in chaos_results if r.success and r.response_json is not None]
    out: list[AssertionResult] = []

    for idx, assertion in enumerate(assertions):
        if isinstance(assertion, SuccessRateAssertion):
            rate = (len(successes) / total) if total else 0.0
            passed = rate >= assertion.min
            detail = f"success_rate={rate:.3f} (min={assertion.min})"
        elif isinstance(assertion, LatencyP95Assertion):
            p95 = _percentile(sorted(r.latency_ms for r in chaos_results), 0.95)
            passed = p95 <= assertion.max
            detail = f"latency_p95_ms={p95:.1f} (max={assertion.max})"
        elif isinstance(assertion, ResponseContainsAssertion):
            failing = [
                r
                for r in successes
                if assertion.forbid_empty and not r.response_json.get(assertion.field)  # type: ignore[union-attr]
            ]
            passed = bool(successes) and not failing
            ok = len(successes) - len(failing)
            detail = (
                f"{ok}/{len(successes)} successful responses had a non-empty '{assertion.field}'"
            )
        elif isinstance(assertion, JsonFieldPresentAssertion):
            failing = [r for r in successes if not _has_min_items(r, assertion)]
            passed = bool(successes) and not failing
            ok = len(successes) - len(failing)
            detail = (
                f"{ok}/{len(successes)} successful responses had "
                f">= {assertion.min_items} '{assertion.field}' item(s)"
            )
        else:  # pragma: no cover - exhaustive over the Assertion union
            passed = False
            detail = "unknown assertion type"

        out.append(AssertionResult(idx=idx, type=assertion.type, passed=passed, detail=detail))
    return out


def _has_min_items(result: RequestResult, assertion: JsonFieldPresentAssertion) -> bool:
    assert result.response_json is not None
    value = result.response_json.get(assertion.field)
    return isinstance(value, list) and len(value) >= assertion.min_items


def tally_fault_fires(metrics_path: Path, *, start_ts: str, end_ts: str) -> dict[str, int]:
    """Count fault fires the proxy logged within a phase's time window."""
    if not metrics_path.exists():
        return {}
    counts: dict[str, int] = {}
    for line in metrics_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        timestamp = record.get("timestamp", "")
        if not (start_ts <= timestamp <= end_ts):
            continue
        for fault_id in record.get("faults_fired", []):
            counts[fault_id] = counts.get(fault_id, 0) + 1
    return counts


def _write_events(events_path: Path, results: list[RequestResult]) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(
                json.dumps(
                    {
                        "phase": r.phase.value,
                        "timestamp": r.timestamp,
                        "status": r.status,
                        "latency_ms": r.latency_ms,
                        "success": r.success,
                        "error_kind": r.error_kind,
                        "response_json": r.response_json,
                    }
                )
                + "\n"
            )


async def run_experiment(
    spec_path: Path,
    *,
    proxy_url: str = "http://127.0.0.1:8000",
    proxy_metrics_path: Path = Path("metrics.jsonl"),
    db_path: Path = Path("chaosllm.db"),
    runs_dir: Path = Path("runs"),
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> RunSummary:
    spec = load_experiment_spec(spec_path)
    run_id = f"{spec.name}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    method, _, path = spec.target.endpoint.partition(" ")
    payloads = load_payloads(spec.target.payload_file)
    events_path = runs_dir / f"{run_id}.jsonl"

    store = MetricsStore(db_path)
    store.create_run(
        run_id=run_id,
        name=spec.name,
        description=spec.description,
        spec_path=str(spec_path),
        started_at=now_iso(),
    )

    all_results: list[RequestResult] = []
    try:
        async with (
            httpx.AsyncClient(base_url=spec.target.base_url) as target_client,
            httpx.AsyncClient(base_url=proxy_url) as control_client,
        ):
            await control_client.delete("/control/faults")

            warmup_start_ts = now_iso()
            warmup_results = await run_load(
                client=target_client,
                method=method,
                url=path,
                payloads=payloads,
                concurrency=spec.load.concurrency,
                duration_s=spec.load.warmup_s,
                phase=Phase.WARMUP,
                request_timeout_s=request_timeout_s,
            )
            warmup_end_ts = now_iso()
            all_results += warmup_results

            if spec.faults:
                faults_body = {"faults": [f.model_dump(mode="json") for f in spec.faults]}
                await control_client.post("/control/faults", json=faults_body)

            chaos_start_ts = now_iso()
            chaos_results = await run_load(
                client=target_client,
                method=method,
                url=path,
                payloads=payloads,
                concurrency=spec.load.concurrency,
                duration_s=spec.load.duration_s,
                phase=Phase.CHAOS,
                request_timeout_s=request_timeout_s,
            )
            chaos_end_ts = now_iso()
            all_results += chaos_results

            await control_client.delete("/control/faults")

            recovery_start_ts = now_iso()
            recovery_results = await run_load(
                client=target_client,
                method=method,
                url=path,
                payloads=payloads,
                concurrency=spec.load.concurrency,
                duration_s=spec.load.warmup_s,
                phase=Phase.RECOVERY,
                request_timeout_s=request_timeout_s,
            )
            recovery_end_ts = now_iso()
            all_results += recovery_results
    except Exception:
        _write_events(events_path, all_results)
        store.finish_run(
            run_id=run_id, finished_at=now_iso(), status="failed", fault_fire_counts={}
        )
        store.close()
        raise

    _write_events(events_path, all_results)

    warmup_fault_fire_counts = tally_fault_fires(
        proxy_metrics_path, start_ts=warmup_start_ts, end_ts=warmup_end_ts
    )
    chaos_fault_fire_counts = tally_fault_fires(
        proxy_metrics_path, start_ts=chaos_start_ts, end_ts=chaos_end_ts
    )
    recovery_fault_fire_counts = tally_fault_fires(
        proxy_metrics_path, start_ts=recovery_start_ts, end_ts=recovery_end_ts
    )

    phase_summaries = [
        summarize_phase(Phase.WARMUP, warmup_results, warmup_fault_fire_counts),
        summarize_phase(Phase.CHAOS, chaos_results, chaos_fault_fire_counts),
        summarize_phase(Phase.RECOVERY, recovery_results, recovery_fault_fire_counts),
    ]
    for summary in phase_summaries:
        store.record_phase_summary(run_id, summary)

    assertion_results = evaluate_assertions(spec.assertions, chaos_results)
    for result in assertion_results:
        store.record_assertion(run_id, result)

    warnings: list[str] = []
    if spec.faults and sum(chaos_fault_fire_counts.values()) == 0:
        warnings.append(ZERO_CHAOS_FAULTS_WARNING.format(n=len(spec.faults)))
    status = "invalid" if warnings else "completed"

    store.finish_run(
        run_id=run_id,
        finished_at=now_iso(),
        status=status,
        fault_fire_counts=chaos_fault_fire_counts,
        warnings=warnings,
    )
    store.close()

    return RunSummary(
        run_id=run_id,
        spec=spec,
        phase_summaries=phase_summaries,
        assertion_results=assertion_results,
        fault_fire_counts=chaos_fault_fire_counts,
        warnings=warnings,
    )
