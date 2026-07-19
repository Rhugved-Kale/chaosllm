"""Unit tests for summarize_phase/evaluate_assertions, focused on
degraded_count/degraded_rate: a phase can show 100% success_rate while every
"success" is a degraded fallback, and that must be visible as its own
number, not folded into success_rate.
"""

from __future__ import annotations

from chaosllm.runner.loadgen import RequestResult
from chaosllm.runner.phases import Phase
from chaosllm.runner.runner import evaluate_assertions, summarize_phase
from chaosllm.spec.models import DegradedRateAssertion, SuccessRateAssertion


def _result(*, success: bool, degraded: bool = False) -> RequestResult:
    return RequestResult(
        phase=Phase.CHAOS,
        timestamp="2026-01-01T00:00:00+00:00",
        status=200 if success else 500,
        latency_ms=7.0 if degraded else 50.0,
        success=success,
        error_kind=None if success else "http_500",
        response_json={"answer": "x", "degraded": degraded} if success else None,
        degraded=degraded,
    )


def test_summarize_phase_counts_degraded_among_successes() -> None:
    results = [
        _result(success=True, degraded=True),
        _result(success=True, degraded=True),
        _result(success=True, degraded=False),
        _result(success=False),
    ]
    summary = summarize_phase(Phase.CHAOS, results, fault_fire_counts={})
    assert summary.success_count == 3
    assert summary.degraded_count == 2
    assert summary.error_count == 1


def test_summarize_phase_degraded_count_zero_when_no_degraded_responses() -> None:
    results = [_result(success=True, degraded=False) for _ in range(3)]
    summary = summarize_phase(Phase.CHAOS, results, fault_fire_counts={})
    assert summary.degraded_count == 0


def test_degraded_rate_assertion_fails_when_all_successes_are_degraded() -> None:
    """The exact scenario reported: 100% success_rate, but every success is
    a degraded fallback answer, e.g. served in single-digit milliseconds."""
    results = [_result(success=True, degraded=True) for _ in range(5)]

    success_rate_result = evaluate_assertions([SuccessRateAssertion(min=0.95)], results)[0]
    assert success_rate_result.passed is True

    degraded_result = evaluate_assertions([DegradedRateAssertion(max=0.5)], results)[0]
    assert degraded_result.passed is False
    assert "degraded_rate=1.000" in degraded_result.detail


def test_degraded_rate_assertion_passes_when_below_threshold() -> None:
    results = [_result(success=True, degraded=False) for _ in range(9)] + [
        _result(success=True, degraded=True)
    ]
    result = evaluate_assertions([DegradedRateAssertion(max=0.5)], results)[0]
    assert result.passed is True
    assert "degraded_rate=0.100" in result.detail


def test_degraded_rate_assertion_with_no_successes_does_not_crash() -> None:
    results = [_result(success=False) for _ in range(3)]
    result = evaluate_assertions([DegradedRateAssertion(max=0.5)], results)[0]
    assert result.passed is True  # vacuously: 0/0 degraded rate is 0.0
