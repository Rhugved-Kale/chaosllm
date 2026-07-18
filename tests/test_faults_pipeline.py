"""FaultPipeline: composition, probability, rate_limit_burst window state."""

from __future__ import annotations

import json
import random

import pytest

from chaosllm.faults.models import (
    ContextOverflowFault,
    ErrorFault,
    LatencyFault,
    MalformedJsonFault,
    ModelDowngradeFault,
    RateLimitBurstFault,
    TimeoutFault,
    TruncateFault,
)
from chaosllm.faults.pipeline import BlackholeResponse, FaultPipeline


async def test_no_active_faults_is_a_noop() -> None:
    pipeline = FaultPipeline()
    outcome = await pipeline.evaluate("/openai/v1/chat/completions", b'{"model":"gpt-4o"}')
    assert outcome.short_circuit is None
    assert outcome.fired == []
    assert outcome.request_body == b'{"model":"gpt-4o"}'


async def test_model_downgrade_rewrites_model_field() -> None:
    pipeline = FaultPipeline()
    pipeline.set_active_faults([ModelDowngradeFault(to_model="gpt-4o-mini", p=1.0)])
    outcome = await pipeline.evaluate(
        "/openai/v1/chat/completions", json.dumps({"model": "gpt-4o", "messages": []}).encode()
    )
    assert json.loads(outcome.request_body) == {"model": "gpt-4o-mini", "messages": []}
    assert outcome.fired == ["model_downgrade"]


async def test_route_glob_only_matches_configured_routes() -> None:
    pipeline = FaultPipeline()
    pipeline.set_active_faults([ErrorFault(status=500, p=1.0, route="/passthrough/vectordb/*")])
    outcome = await pipeline.evaluate("/openai/v1/chat/completions", b"{}")
    assert outcome.short_circuit is None

    outcome2 = await pipeline.evaluate("/passthrough/vectordb/health", b"{}")
    assert outcome2.short_circuit is not None
    assert outcome2.short_circuit.status_code == 500


async def test_error_fault_short_circuits_with_pinned_shape() -> None:
    pipeline = FaultPipeline()
    pipeline.set_active_faults([ErrorFault(status=429, p=1.0)])
    outcome = await pipeline.evaluate("/openai/v1/chat/completions", b"{}")
    assert outcome.short_circuit is not None
    assert outcome.short_circuit.status_code == 429
    assert outcome.fired == ["error"]


async def test_error_fault_body_override() -> None:
    pipeline = FaultPipeline()
    pipeline.set_active_faults([ErrorFault(status=500, p=1.0, body={"custom": True})])
    outcome = await pipeline.evaluate("/openai/v1/chat/completions", b"{}")
    assert outcome.short_circuit is not None
    assert json.loads(outcome.short_circuit.body) == {"custom": True}


async def test_context_overflow_short_circuits() -> None:
    pipeline = FaultPipeline()
    pipeline.set_active_faults([ContextOverflowFault(p=1.0)])
    outcome = await pipeline.evaluate("/anthropic/v1/messages", b"{}")
    assert outcome.short_circuit is not None
    assert outcome.short_circuit.status_code == 400
    assert outcome.fired == ["context_overflow"]


async def test_timeout_fault_returns_blackhole_response() -> None:
    pipeline = FaultPipeline()
    pipeline.set_active_faults([TimeoutFault(hold_ms=10, p=1.0)])
    outcome = await pipeline.evaluate("/openai/v1/chat/completions", b"{}")
    assert isinstance(outcome.short_circuit, BlackholeResponse)
    assert outcome.fired == ["timeout"]


async def test_blackhole_response_never_calls_send() -> None:
    calls: list[object] = []

    async def send(message: object) -> None:
        calls.append(message)

    async def receive() -> dict[str, object]:
        return {}

    blackhole = BlackholeResponse(hold_seconds=0.01)
    await blackhole({}, receive, send)
    assert calls == []


async def test_truncate_shrinks_body() -> None:
    pipeline = FaultPipeline()
    pipeline.set_active_faults([TruncateFault(keep_fraction=0.5, p=1.0)])
    body = b'{"answer": "a fairly long response body here"}'
    outcome = await pipeline.evaluate("/openai/v1/chat/completions", body)
    assert outcome.response_transform is not None
    transformed = outcome.response_transform.apply(body)
    assert len(transformed) == len(body) // 2


@pytest.mark.parametrize("mode", ["drop_closing_brace", "mangle_key"])
async def test_malformed_json_breaks_parsing(mode: str) -> None:
    pipeline = FaultPipeline()
    pipeline.set_active_faults([MalformedJsonFault(mode=mode, p=1.0)])
    body = json.dumps({"id": "abc", "choices": []}).encode()
    outcome = await pipeline.evaluate("/openai/v1/chat/completions", body)
    assert outcome.response_transform is not None
    transformed = outcome.response_transform.apply(body)

    json.loads(body)  # sanity: original is valid
    with pytest.raises(json.JSONDecodeError):
        json.loads(transformed)


async def test_latency_fault_sets_pre_delay() -> None:
    pipeline = FaultPipeline()
    pipeline.set_active_faults([LatencyFault(delay_ms=100, jitter_ms=20, p=1.0)])
    outcome = await pipeline.evaluate("/openai/v1/chat/completions", b"{}")
    assert 0.08 <= outcome.pre_delay_s <= 0.12
    assert outcome.fired == ["latency"]


async def test_probability_is_respected_statistically() -> None:
    pipeline = FaultPipeline(rng=random.Random(0))
    pipeline.set_active_faults([ErrorFault(status=500, p=0.3)])

    trials = 4000
    fired = 0
    for _ in range(trials):
        outcome = await pipeline.evaluate("/openai/v1/chat/completions", b"{}")
        if outcome.short_circuit is not None:
            fired += 1

    rate = fired / trials
    assert 0.25 <= rate <= 0.35


async def test_rate_limit_burst_blocks_after_limit_and_resets_on_window_boundary() -> None:
    clock = {"t": 0.0}
    pipeline = FaultPipeline(time_fn=lambda: clock["t"])
    pipeline.set_active_faults([RateLimitBurstFault(limit=3, window_s=10.0)])

    for t in (0.0, 1.0, 2.0):
        clock["t"] = t
        outcome = await pipeline.evaluate("/openai/v1/chat/completions", b"{}")
        assert outcome.short_circuit is None, f"request at t={t} should be under the limit"

    clock["t"] = 3.0
    blocked_outcome = await pipeline.evaluate("/openai/v1/chat/completions", b"{}")
    assert blocked_outcome.short_circuit is not None
    assert blocked_outcome.short_circuit.status_code == 429
    assert blocked_outcome.fired == ["rate_limit_burst"]

    # Just before the window resets, still blocked.
    clock["t"] = 9.9
    still_blocked = await pipeline.evaluate("/openai/v1/chat/completions", b"{}")
    assert still_blocked.short_circuit is not None

    # At the window boundary, the counter resets.
    clock["t"] = 10.0
    reset_outcome = await pipeline.evaluate("/openai/v1/chat/completions", b"{}")
    assert reset_outcome.short_circuit is None
