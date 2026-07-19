"""In-memory SSE event bus for live run progress (DESIGN.md 4.7: dashboard
"Connects to the control API via SSE (GET /control/runs/{id}/events)").

The runner pushes progress snapshots to the proxy's control API as it
drives an experiment; the dashboard subscribes to the same run_id here and
gets them fanned out as they arrive. One asyncio.Queue per subscriber, no
persistence, no cross-process delivery: a proxy restart drops every
subscriber and any events published so far. Fine for a live dashboard (the
browser just reconnects and picks up the next tick), not a durable audit
log, that's what the SQLite store and JSONL logs are for.
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

    @property
    def latest_run_id(self) -> str | None:
        return self._latest_run_id

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        self._latest_run_id = run_id
        for queue in self._subscribers.get(run_id, ()):
            queue.put_nowait(event)

    async def subscribe(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.get("type") == RUN_COMPLETE_EVENT_TYPE:
                    break
        finally:
            self._subscribers[run_id].discard(queue)
