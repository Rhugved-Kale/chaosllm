"""Resilience report: Markdown and JSON, rendered from the SQLite summary
store (DESIGN.md 4.5). The money artifact is the one-line finding: baseline
success rate vs. chaos success rate, plus what actually broke.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from chaosllm.metrics.store import MetricsStore, PhaseSummary
from chaosllm.report.charts import render_latency_svg


class RunNotFoundError(Exception):
    pass


def _phase_row(summary: PhaseSummary) -> str:
    success_rate = summary.success_count / summary.total_count if summary.total_count else 0.0
    p50 = f"{summary.latency_p50_ms:.0f}" if summary.latency_p50_ms is not None else "-"
    p95 = f"{summary.latency_p95_ms:.0f}" if summary.latency_p95_ms is not None else "-"
    p99 = f"{summary.latency_p99_ms:.0f}" if summary.latency_p99_ms is not None else "-"
    faults_fired = sum(summary.fault_fire_counts.values())
    return (
        f"| {summary.phase} | {summary.total_count} | {success_rate:.1%} "
        f"| {p50} | {p95} | {p99} | {faults_fired} |"
    )


def _error_taxonomy_lines(phase_summaries: list[PhaseSummary]) -> list[str]:
    lines = []
    for summary in phase_summaries:
        if not summary.error_taxonomy or summary.error_count == 0:
            continue
        parts = [
            f"{count / summary.error_count:.0%} {kind}"
            for kind, count in sorted(summary.error_taxonomy.items(), key=lambda kv: -kv[1])
        ]
        lines.append(f"- **{summary.phase}**: {', '.join(parts)}")
    return lines


def _summary_sentence(phase_summaries: list[PhaseSummary]) -> str | None:
    by_phase = {s.phase: s for s in phase_summaries}
    warmup = by_phase.get("warmup")
    chaos = by_phase.get("chaos")
    if warmup is None or chaos is None or warmup.total_count == 0 or chaos.total_count == 0:
        return None

    warmup_rate = warmup.success_count / warmup.total_count
    chaos_rate = chaos.success_count / chaos.total_count
    sentence = (
        f"Success rate dropped from {warmup_rate:.1%} (baseline) to {chaos_rate:.1%} under chaos."
    )
    if chaos.error_taxonomy and chaos.error_count:
        top_kind, top_count = max(chaos.error_taxonomy.items(), key=lambda kv: kv[1])
        sentence += f" {top_count / chaos.error_count:.0%} of failures were {top_kind}."
    return sentence


def render_markdown(store: MetricsStore, run_id: str) -> str:
    run = store.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    phase_summaries = store.get_phase_summaries(run_id)
    assertions = store.get_assertions(run_id)

    lines = [
        f"# Resilience report: {run.name}",
        "",
        run.description or "_(no description)_",
        "",
        f"- run id: `{run.run_id}`",
        f"- status: {run.status}",
        f"- started: {run.started_at}",
        f"- finished: {run.finished_at or '-'}",
    ]

    if run.warnings:
        lines += ["", "## Warnings", ""]
        lines += [f"- {warning}" for warning in run.warnings]

    lines += [
        "",
        "## Per-phase results",
        "",
        "| phase | requests | success rate | p50 ms | p95 ms | p99 ms | faults fired |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [_phase_row(s) for s in phase_summaries]

    taxonomy_lines = _error_taxonomy_lines(phase_summaries)
    if taxonomy_lines:
        lines += ["", "## Error taxonomy", "", *taxonomy_lines]

    lines += ["", "## Assertions", ""]
    if assertions:
        for assertion in assertions:
            mark = "PASS" if assertion.passed else "FAIL"
            lines.append(f"- [{mark}] `{assertion.type}`: {assertion.detail}")
    else:
        lines.append("_(no assertions configured)_")

    if run.fault_fire_counts:
        lines += ["", "## Faults fired during chaos phase", ""]
        for fault_id, count in sorted(run.fault_fire_counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{fault_id}`: {count}")

    summary_sentence = _summary_sentence(phase_summaries)
    if summary_sentence:
        lines += ["", "## Summary", "", summary_sentence]

    svg = render_latency_svg(phase_summaries)
    if svg:
        lines += ["", "## Degradation profile", "", svg]

    return "\n".join(lines) + "\n"


def render_json(store: MetricsStore, run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return {
        "run": asdict(run),
        "phases": [asdict(s) for s in store.get_phase_summaries(run_id)],
        "assertions": [asdict(a) for a in store.get_assertions(run_id)],
    }
