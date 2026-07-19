"""Budget tracker: cost estimation from provider usage, cap enforcement,
daily UTC reset (DESIGN.md 5: "hard daily budget cap enforced in the proxy")."""

from __future__ import annotations

from datetime import UTC, datetime

from chaosllm.proxy.budget import (
    BudgetTracker,
    UsageEstimate,
    estimate_cost_usd,
    parse_usage,
)


def test_estimate_cost_for_known_model() -> None:
    cost = estimate_cost_usd(
        "claude-haiku-4-5", UsageEstimate(input_tokens=1_000, output_tokens=500)
    )
    # $1/MTok input + $5/MTok output
    assert cost == (1_000 * 1.00 + 500 * 5.00) / 1_000_000


def test_estimate_cost_for_unknown_model_uses_fallback_rate() -> None:
    known = estimate_cost_usd(
        "claude-haiku-4-5", UsageEstimate(input_tokens=1_000, output_tokens=0)
    )
    unknown = estimate_cost_usd(
        "some-future-model", UsageEstimate(input_tokens=1_000, output_tokens=0)
    )
    assert unknown == known  # fallback happens to match the haiku rate today


def test_parse_usage_openai_shape() -> None:
    usage = parse_usage("openai", {"usage": {"prompt_tokens": 10, "completion_tokens": 20}})
    assert usage == UsageEstimate(input_tokens=10, output_tokens=20)


def test_parse_usage_anthropic_shape() -> None:
    usage = parse_usage("anthropic", {"usage": {"input_tokens": 10, "output_tokens": 20}})
    assert usage == UsageEstimate(input_tokens=10, output_tokens=20)


def test_parse_usage_missing_returns_none() -> None:
    assert parse_usage("openai", {"choices": []}) is None
    assert parse_usage("openai", {"usage": {"prompt_tokens": "not-a-number"}}) is None


def test_no_cap_is_never_exhausted() -> None:
    tracker = BudgetTracker(daily_cap_usd=None)
    assert tracker.is_exhausted() is False


async def test_exhausted_once_spend_reaches_cap() -> None:
    tracker = BudgetTracker(daily_cap_usd=1.0)
    assert tracker.is_exhausted() is False
    await tracker.add_cost(0.5)
    assert tracker.is_exhausted() is False
    await tracker.add_cost(0.5)
    assert tracker.is_exhausted() is True


async def test_resets_at_utc_midnight() -> None:
    clock = {"now": datetime(2026, 1, 1, 23, 0, tzinfo=UTC)}
    tracker = BudgetTracker(daily_cap_usd=1.0, now_fn=lambda: clock["now"])

    await tracker.add_cost(1.0)
    assert tracker.is_exhausted() is True

    clock["now"] = datetime(2026, 1, 2, 0, 5, tzinfo=UTC)
    assert tracker.is_exhausted() is False
    assert tracker.spent_usd == 0.0
