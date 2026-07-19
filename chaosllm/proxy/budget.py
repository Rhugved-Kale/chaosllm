"""Daily spend cap for the hosted proxy (DESIGN.md 5): "Hosted demo uses a
low-cost model ... with a hard daily budget cap enforced in the proxy (spend
tracker, returns 402 past cap)."

Token counts come straight from each provider's own `usage` object in the
response body, so the estimate is only as good as that self-reported count.
The per-token prices below are pinned from each provider's current pricing
page (linked) and exist to keep a public demo from draining a card
overnight, not for billing-grade accuracy; see the README limitations
section for what this does and doesn't guarantee.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

# Per-million-token USD prices (input, output), pinned to the two models
# this project's demo actually defaults to.
# https://platform.claude.com/docs/en/about-claude/pricing
# https://developers.openai.com/api/docs/pricing
_PRICE_PER_MTOK_USD: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-5.4-mini": (0.75, 4.50),
}
# Unrecognized model: bill at the more expensive of the two known rates
# rather than guess low and undercount spend against the cap.
_FALLBACK_PRICE_PER_MTOK_USD = (1.00, 5.00)

BUDGET_EXCEEDED_STATUS = 402


@dataclass(frozen=True)
class UsageEstimate:
    input_tokens: int
    output_tokens: int


def estimate_cost_usd(model: str, usage: UsageEstimate) -> float:
    input_price, output_price = _PRICE_PER_MTOK_USD.get(model, _FALLBACK_PRICE_PER_MTOK_USD)
    return (usage.input_tokens * input_price + usage.output_tokens * output_price) / 1_000_000


def parse_usage(provider: str, body: dict[str, Any]) -> UsageEstimate | None:
    """Best-effort token usage extraction from a provider's JSON response body.

    Returns None (no cost added) if `usage` is missing or unrecognized shape,
    e.g. a non-2xx response, rather than guessing.
    """
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None
    if provider == "anthropic":
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
    else:
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    return UsageEstimate(input_tokens=input_tokens, output_tokens=output_tokens)


def budget_exceeded_body(daily_cap_usd: float) -> dict[str, Any]:
    return {
        "error": {
            "message": (
                f"Daily budget of ${daily_cap_usd:.2f} exhausted for this demo. "
                "Try again after 00:00 UTC."
            ),
            "type": "budget_exceeded",
        }
    }


class BudgetTracker:
    """Tracks estimated spend against a daily USD cap, reset at UTC midnight.

    In-memory only: a proxy restart resets the counter early. Acceptable for
    a v0.1 hosted demo (documented in the README limitations section), not
    something to rely on for real billing enforcement.
    """

    def __init__(
        self,
        daily_cap_usd: float | None,
        *,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.daily_cap_usd = daily_cap_usd
        self._now_fn = now_fn
        self._spent_usd = 0.0
        self._day: date = now_fn().date()
        self._lock = asyncio.Lock()

    def _maybe_reset(self) -> None:
        today = self._now_fn().date()
        if today != self._day:
            self._day = today
            self._spent_usd = 0.0

    @property
    def spent_usd(self) -> float:
        self._maybe_reset()
        return self._spent_usd

    def is_exhausted(self) -> bool:
        if self.daily_cap_usd is None:
            return False
        return self.spent_usd >= self.daily_cap_usd

    async def add_cost(self, cost_usd: float) -> None:
        async with self._lock:
            self._maybe_reset()
            self._spent_usd += cost_usd


def budget_tracker_from_env() -> BudgetTracker:
    raw = os.environ.get("BUDGET_DAILY_USD", "").strip()
    daily_cap_usd = float(raw) if raw else None
    return BudgetTracker(daily_cap_usd=daily_cap_usd)
