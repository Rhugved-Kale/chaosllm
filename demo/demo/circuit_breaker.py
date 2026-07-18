"""A minimal circuit breaker for the resilient LLM call path.

Opens after `failure_threshold` consecutive failures; while open, calls are
rejected immediately (no network hit) for `reset_after_s`, then the breaker
moves to half-open and lets the next call through as a trial.
"""

from __future__ import annotations

import time
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 3, reset_after_s: float = 5.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_after_s = reset_after_s
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        if self._opened_at is None:
            return CircuitState.CLOSED
        if time.monotonic() - self._opened_at >= self.reset_after_s:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def before_call(self) -> None:
        if self.state == CircuitState.OPEN:
            raise CircuitOpenError("circuit is open")

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            # Re-arm the cooldown on every qualifying failure, not just the
            # first: a half-open trial that fails again must re-open the
            # circuit, or it silently stays half-open (a real call attempted
            # every time) for good after the first cooldown ever elapses.
            self._opened_at = time.monotonic()
