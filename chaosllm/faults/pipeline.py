"""FaultPipeline: the active fault set, evaluated in a fixed order per request.

DESIGN.md 4.1: "Faults are middlewares in a pipeline. Each request passes
through the active fault set; each fault decides independently (probability
per fault) whether to fire."

Fixed evaluation order (documented here, not configurable in v0.1):

  1. model_downgrade   - mutates the request body's `model` field
  2. rate_limit_burst  - stateful window check (not probabilistic)
  3. context_overflow  - synthetic error, short-circuits
  4. error             - synthetic error, short-circuits
  5. timeout           - blackhole, short-circuits
  6. truncate          - mutates the response body (only if not short-circuited)
  7. malformed_json    - mutates the response body (only if not short-circuited)
  8. latency           - delay, applied last regardless of outcome

Only one short-circuiting fault can win per request: the first one (in the
order above) whose check fires. rate_limit_burst goes first because it is
deterministic state, closer to how a real upstream would behave, rather than
a coin flip.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from starlette.responses import Response

from chaosllm.faults import provider_shapes
from chaosllm.faults.models import (
    ContextOverflowFault,
    ErrorFault,
    FaultConfig,
    LatencyFault,
    MalformedJsonFault,
    ModelDowngradeFault,
    RateLimitBurstFault,
    TimeoutFault,
    TruncateFault,
)


class BlackholeResponse(Response):
    """Holds the connection open for `hold_seconds`, then sends nothing.

    Simulates DESIGN.md 4.2's `timeout` fault ("accept request, never respond
    until client gives up"). Overriding `__call__` instead of raising lets
    this skip Starlette's ServerErrorMiddleware, which would otherwise turn
    an unhandled exception into a real 500 and defeat the point: the client
    should see nothing, not an error.
    """

    def __init__(self, hold_seconds: float) -> None:
        super().__init__(status_code=599)
        self.hold_seconds = hold_seconds

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await asyncio.sleep(self.hold_seconds)


@dataclass
class ResponseTransform:
    truncate_keep_fraction: float | None = None
    malformed_json_mode: str | None = None

    def apply(self, body: bytes) -> bytes:
        if self.truncate_keep_fraction is not None:
            keep = int(len(body) * self.truncate_keep_fraction)
            body = body[:keep]
        if self.malformed_json_mode == "drop_closing_brace":
            body = _drop_closing_brace(body)
        elif self.malformed_json_mode == "mangle_key":
            body = _mangle_key(body)
        return body


@dataclass
class FaultOutcome:
    request_body: bytes
    short_circuit: Response | None = None
    pre_delay_s: float = 0.0
    response_transform: ResponseTransform | None = None
    fired: list[str] = field(default_factory=list)


@dataclass
class _RateLimitWindow:
    window_start: float
    count: int


def _provider_for(route_path: str) -> str:
    return "anthropic" if route_path.startswith("/anthropic") else "openai"


def _drop_closing_brace(body: bytes) -> bytes:
    text = body.decode("utf-8", errors="ignore").rstrip()
    if text.endswith("}"):
        text = text[:-1]
    return text.encode("utf-8")


def _mangle_key(body: bytes) -> bytes:
    """Drop the closing quote of the first JSON key, e.g. `"id":` -> `"id:`."""
    text = body.decode("utf-8", errors="ignore")
    idx = text.find('":')
    if idx == -1:
        return body
    text = text[:idx] + text[idx + 1 :]
    return text.encode("utf-8")


def _rewrite_model(body: bytes, to_model: str) -> bytes:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body
    if isinstance(data, dict) and "model" in data:
        data["model"] = to_model
        return json.dumps(data).encode("utf-8")
    return body


class FaultPipeline:
    """Holds the currently active fault set and evaluates it per request.

    `time_fn` and `rng` are injectable so tests can control the clock
    (rate_limit_burst window boundaries) and randomness (probability `p`)
    deterministically instead of sleeping or looping for statistical luck.
    """

    def __init__(
        self,
        *,
        time_fn: Any = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self._active: list[FaultConfig] = []
        self._time_fn = time_fn
        self._rng = rng or random.Random()
        self._rate_limit_windows: dict[int, _RateLimitWindow] = {}

    @property
    def active_faults(self) -> list[FaultConfig]:
        return list(self._active)

    def set_active_faults(self, faults: list[FaultConfig]) -> None:
        self._active = faults
        self._rate_limit_windows = {}

    def clear(self) -> None:
        self._active = []
        self._rate_limit_windows = {}

    def _matching(self, route_path: str, fault_type: type[Any]) -> list[Any]:
        return [
            f
            for f in self._active
            if isinstance(f, fault_type) and fnmatchcase(route_path, f.route)
        ]

    def _rolls(self, p: float) -> bool:
        return self._rng.random() < p

    def _error_response(
        self,
        route_path: str,
        status: int,
        *,
        retry_after_s: int | None = None,
        body_override: dict[str, object] | None = None,
    ) -> Response:
        if body_override is not None:
            shape = provider_shapes.ErrorShape(status=status, body=body_override)
        elif _provider_for(route_path) == "anthropic":
            shape = provider_shapes.anthropic_error(status, retry_after_s=retry_after_s)
        else:
            shape = provider_shapes.openai_error(status, retry_after_s=retry_after_s)
        return Response(
            content=json.dumps(shape.body),
            status_code=shape.status,
            headers={**shape.headers, "content-type": "application/json"},
        )

    def _context_overflow_response(self, route_path: str) -> Response:
        shape = (
            provider_shapes.anthropic_context_overflow()
            if _provider_for(route_path) == "anthropic"
            else provider_shapes.openai_context_length_exceeded()
        )
        return Response(
            content=json.dumps(shape.body),
            status_code=shape.status,
            headers={**shape.headers, "content-type": "application/json"},
        )

    def _check_rate_limit(self, fault: RateLimitBurstFault) -> tuple[bool, float]:
        """Fixed-window counter. Returns (blocked, seconds_left_in_window)."""
        now = self._time_fn()
        key = id(fault)
        window = self._rate_limit_windows.get(key)
        if window is None or now - window.window_start >= fault.window_s:
            window = _RateLimitWindow(window_start=now, count=0)
            self._rate_limit_windows[key] = window
        window.count += 1
        if window.count > fault.limit:
            return True, fault.window_s - (now - window.window_start)
        return False, 0.0

    def _try_rate_limit_burst(self, route_path: str) -> tuple[Response | None, str | None]:
        for fault in self._matching(route_path, RateLimitBurstFault):
            blocked, retry_after = self._check_rate_limit(fault)
            if blocked:
                response = self._error_response(
                    route_path, 429, retry_after_s=max(int(retry_after) + 1, 1)
                )
                return response, "rate_limit_burst"
        return None, None

    def _try_context_overflow(self, route_path: str) -> tuple[Response | None, str | None]:
        for fault in self._matching(route_path, ContextOverflowFault):
            if self._rolls(fault.p):
                return self._context_overflow_response(route_path), "context_overflow"
        return None, None

    def _try_error(self, route_path: str) -> tuple[Response | None, str | None]:
        for fault in self._matching(route_path, ErrorFault):
            if self._rolls(fault.p):
                response = self._error_response(route_path, fault.status, body_override=fault.body)
                return response, "error"
        return None, None

    def _try_timeout(self, route_path: str) -> tuple[Response | None, str | None]:
        for fault in self._matching(route_path, TimeoutFault):
            if self._rolls(fault.p):
                return BlackholeResponse(fault.hold_ms / 1000), "timeout"
        return None, None

    async def evaluate(self, route_path: str, request_body: bytes) -> FaultOutcome:
        outcome = FaultOutcome(request_body=request_body)

        for fault in self._matching(route_path, ModelDowngradeFault):
            if self._rolls(fault.p):
                outcome.request_body = _rewrite_model(outcome.request_body, fault.to_model)
                outcome.fired.append("model_downgrade")
                break

        for try_fn in (
            self._try_rate_limit_burst,
            self._try_context_overflow,
            self._try_error,
            self._try_timeout,
        ):
            response, fault_id = try_fn(route_path)
            if response is not None:
                outcome.short_circuit = response
                assert fault_id is not None
                outcome.fired.append(fault_id)
                break

        if outcome.short_circuit is None:
            transform = ResponseTransform()
            for fault in self._matching(route_path, TruncateFault):
                if self._rolls(fault.p):
                    transform.truncate_keep_fraction = fault.keep_fraction
                    outcome.fired.append("truncate")
                    break
            for fault in self._matching(route_path, MalformedJsonFault):
                if self._rolls(fault.p):
                    transform.malformed_json_mode = fault.mode
                    outcome.fired.append("malformed_json")
                    break
            transform_is_active = (
                transform.truncate_keep_fraction is not None
                or transform.malformed_json_mode is not None
            )
            if transform_is_active:
                outcome.response_transform = transform

        for fault in self._matching(route_path, LatencyFault):
            if self._rolls(fault.p):
                delay_ms = fault.delay_ms
                if fault.jitter_ms:
                    delay_ms += self._rng.uniform(-fault.jitter_ms, fault.jitter_ms)
                outcome.pre_delay_s = max(delay_ms, 0.0) / 1000
                outcome.fired.append("latency")
                break

        return outcome
