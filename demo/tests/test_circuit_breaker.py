"""CircuitBreaker: opens on threshold, half-opens after cooldown, and
crucially re-opens if a half-open trial fails too (found via manual testing:
without this, the breaker permanently stays half-open after its first
cooldown, attempting a real call on every request during a sustained outage,
defeating the whole point of "stop hammering a dead upstream")."""

from __future__ import annotations

import time

from demo.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


def test_opens_after_threshold_consecutive_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=3, reset_after_s=5.0)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN


def test_before_call_raises_while_open() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_after_s=5.0)
    breaker.record_failure()
    try:
        breaker.before_call()
        raise AssertionError("expected CircuitOpenError")
    except CircuitOpenError:
        pass


def test_success_resets_to_closed() -> None:
    breaker = CircuitBreaker(failure_threshold=2, reset_after_s=5.0)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


def test_half_open_trial_failure_reopens_the_circuit() -> None:
    reset_after_s = 0.05
    breaker = CircuitBreaker(failure_threshold=1, reset_after_s=reset_after_s)
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    time.sleep(reset_after_s * 1.5)
    assert breaker.state == CircuitState.HALF_OPEN  # cooldown elapsed, one trial allowed

    # The half-open trial call fails: this must re-arm the cooldown, not
    # leave the breaker permanently half-open (a real call attempted every
    # time) for the rest of the outage.
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    time.sleep(reset_after_s * 1.5)
    assert breaker.state == CircuitState.HALF_OPEN
