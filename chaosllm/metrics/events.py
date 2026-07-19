"""In-memory SSE event bus for live run progress (DESIGN.md 4.7: dashboard
"Connects to the control API via SSE (GET /control/runs/{id}/events)").

The runner pushes progress snapshots to the proxy's control API as it
drives an experiment; the dashboard subscribes to the same run_id here and
gets them fanned out as they arrive. No persistence, no cross-process
delivery: a proxy restart drops every subscriber and any events published
so far. Not a durable audit log, that's what the SQLite store and JSONL
logs are for.

One thing worth keeping even in an ephemeral bus: the last event published
per run_id. A subscriber that attaches after some (or all) events for a run
have already gone out - a dashboard tab opened or refreshed between runs,
or mid-run - would otherwise see nothing at all until the next event, or
forever if the run has already finished. Replaying that one snapshot on
attach gives every subscriber the current state immediately, at the cost of
possibly emitting the same "latest" event to two racing subscribers rather
than none.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

RUN_COMPLETE_EVENT_TYPE = "run_complete"


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._latest_run_id: str | None = None
        self._last_event: dict[str, dict[str, Any]] = {}

    @property
    def latest_run_id(self) -> str | None:
        return self._latest_run_id

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        self._latest_run_id = run_id
        self._last_event[run_id] = event
        for queue in self._subscribers.get(run_id, ()):
            queue.put_nowait(event)

    async def subscribe(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        # No await between this read and registering the queue below, so no
        # other coroutine can publish in between: replaying last_event first
        # can't lose or duplicate whatever's next in the queue.
        last_event = self._last_event.get(run_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        try:
            if last_event is not None:
                yield last_event
                if last_event.get("type") == RUN_COMPLETE_EVENT_TYPE:
                    return
            while True:
                event = await queue.get()
                yield event
                if event.get("type") == RUN_COMPLETE_EVENT_TYPE:
                    break
        finally:
            self._subscribers[run_id].discard(queue)
