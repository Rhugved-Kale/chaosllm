"""EventBus: publish/subscribe fan-out, stream ends on run_complete."""

from __future__ import annotations

import asyncio

from chaosllm.metrics.events import EventBus


async def test_subscriber_receives_published_events() -> None:
    bus = EventBus()

    async def collect() -> list[dict[str, object]]:
        return [event async for event in bus.subscribe("run-1")]

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.01)  # let the subscriber register
    bus.publish("run-1", {"type": "progress", "phase": "chaos"})
    bus.publish("run-1", {"type": "run_complete"})

    events = await asyncio.wait_for(task, timeout=1.0)
    assert events == [{"type": "progress", "phase": "chaos"}, {"type": "run_complete"}]


async def test_events_for_other_run_ids_are_not_delivered() -> None:
    bus = EventBus()

    async def collect() -> list[dict[str, object]]:
        return [event async for event in bus.subscribe("run-a")]

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.01)
    bus.publish("run-b", {"type": "progress"})
    bus.publish("run-a", {"type": "run_complete"})

    events = await asyncio.wait_for(task, timeout=1.0)
    assert events == [{"type": "run_complete"}]


async def test_latest_run_id_tracks_most_recent_publish() -> None:
    bus = EventBus()
    assert bus.latest_run_id is None
    bus.publish("run-1", {"type": "progress"})
    assert bus.latest_run_id == "run-1"
    bus.publish("run-2", {"type": "progress"})
    assert bus.latest_run_id == "run-2"


async def test_multiple_subscribers_to_the_same_run_each_get_events() -> None:
    bus = EventBus()

    async def collect() -> list[dict[str, object]]:
        return [event async for event in bus.subscribe("run-1")]

    task_a = asyncio.create_task(collect())
    task_b = asyncio.create_task(collect())
    await asyncio.sleep(0.01)
    bus.publish("run-1", {"type": "run_complete"})

    events_a, events_b = await asyncio.gather(
        asyncio.wait_for(task_a, timeout=1.0), asyncio.wait_for(task_b, timeout=1.0)
    )
    assert events_a == [{"type": "run_complete"}]
    assert events_b == [{"type": "run_complete"}]
