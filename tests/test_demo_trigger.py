"""DemoTrigger: the server-side gate behind the dashboard's "Run a live
experiment" button - a sliding one-hour rate limit plus a single-in-flight
guard, independent of the budget cap."""

from __future__ import annotations

import pytest

from chaosllm.proxy.demo_trigger import DemoTrigger, demo_trigger_from_env


async def test_allows_up_to_the_hourly_limit() -> None:
    clock = {"now": 0.0}
    trigger = DemoTrigger(
        demo_app_url="http://demo.internal", max_per_hour=2, now_fn=lambda: clock["now"]
    )

    first = await trigger.try_start()
    assert first.allowed is True
    await trigger.finish()

    second = await trigger.try_start()
    assert second.allowed is True
    await trigger.finish()

    third = await trigger.try_start()
    assert third.allowed is False
    assert third.reason == "rate_limited"
    assert third.retry_after_s > 0


async def test_old_starts_fall_out_of_the_one_hour_window() -> None:
    clock = {"now": 0.0}
    trigger = DemoTrigger(
        demo_app_url="http://demo.internal", max_per_hour=1, now_fn=lambda: clock["now"]
    )

    await trigger.try_start()
    await trigger.finish()

    clock["now"] = 3601.0  # just past the one-hour window
    decision = await trigger.try_start()
    assert decision.allowed is True


async def test_refuses_a_second_run_while_one_is_in_flight() -> None:
    trigger = DemoTrigger(demo_app_url="http://demo.internal", max_per_hour=10)

    first = await trigger.try_start()
    assert first.allowed is True

    second = await trigger.try_start()
    assert second.allowed is False
    assert second.reason == "already_running"

    await trigger.finish()
    third = await trigger.try_start()
    assert third.allowed is True


def test_from_env_disabled_when_demo_app_url_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_APP_URL", raising=False)
    assert demo_trigger_from_env() is None


def test_from_env_reads_configured_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_APP_URL", "http://demo-app.railway.internal:8080")
    monkeypatch.setenv("DEMO_TRIGGER_MAX_PER_HOUR", "6")
    trigger = demo_trigger_from_env()
    assert trigger is not None
    assert trigger.demo_app_url == "http://demo-app.railway.internal:8080"
    assert trigger.max_per_hour == 6


def test_from_env_defaults_max_per_hour_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_APP_URL", "http://demo-app.railway.internal:8080")
    monkeypatch.delenv("DEMO_TRIGGER_MAX_PER_HOUR", raising=False)
    trigger = demo_trigger_from_env()
    assert trigger is not None
    assert trigger.max_per_hour == 4
