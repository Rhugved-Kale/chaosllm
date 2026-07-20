"""Server-side gate for the dashboard's "Run a live experiment" button.

That button hits an unauthenticated, public endpoint that kicks off a real,
cost-bearing experiment against the hosted demo app. BUDGET_DAILY_USD is
already a hard backstop on total spend, but without a rate limit specific
to this button, a burst of clicks (or a bot) could still fire many
overlapping runs in a row before the budget cap ever kicks in, each one
competing for the same demo app and muddying the dashboard's "latest run"
with interleaved event streams. This tracks recent trigger timestamps in a
simple sliding one-hour window, independent of budget, and refuses a new
run while one it started is still in flight.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SPEC_PATH = Path("experiments/quick-demo.yaml")
DEFAULT_MAX_PER_HOUR = 4
_WINDOW_S = 3600.0


@dataclass(frozen=True)
class TriggerDecision:
    allowed: bool
    reason: str = ""
    retry_after_s: int = 0


class DemoTrigger:
    """In-memory only, same caveat as BudgetTracker: a proxy restart resets
    the window early. Acceptable for a v0.1 rate limit, not a durable one.
    """

    def __init__(
        self,
        *,
        demo_app_url: str,
        spec_path: Path = DEFAULT_SPEC_PATH,
        max_per_hour: int = DEFAULT_MAX_PER_HOUR,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.demo_app_url = demo_app_url
        self.spec_path = spec_path
        self.max_per_hour = max_per_hour
        self._now_fn = now_fn
        self._recent_starts: list[float] = []
        self._running = False
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - _WINDOW_S
        self._recent_starts = [t for t in self._recent_starts if t > cutoff]

    async def try_start(self) -> TriggerDecision:
        async with self._lock:
            now = self._now_fn()
            self._prune(now)
            if self._running:
                return TriggerDecision(False, "already_running")
            if len(self._recent_starts) >= self.max_per_hour:
                oldest = min(self._recent_starts)
                retry_after_s = max(1, int(oldest + _WINDOW_S - now) + 1)
                return TriggerDecision(False, "rate_limited", retry_after_s)
            self._recent_starts.append(now)
            self._running = True
            return TriggerDecision(True)

    async def finish(self) -> None:
        async with self._lock:
            self._running = False


def demo_trigger_from_env() -> DemoTrigger | None:
    """None means the feature is off: no DEMO_APP_URL configured, which is
    the case for local dev and for anyone else's deployment of this repo
    that hasn't set it up. The endpoint reports this plainly rather than
    pretending the button would work.
    """
    demo_app_url = os.environ.get("DEMO_APP_URL", "").strip()
    if not demo_app_url:
        return None
    max_per_hour_raw = os.environ.get("DEMO_TRIGGER_MAX_PER_HOUR", "").strip()
    max_per_hour = int(max_per_hour_raw) if max_per_hour_raw else DEFAULT_MAX_PER_HOUR
    return DemoTrigger(demo_app_url=demo_app_url, max_per_hour=max_per_hour)
