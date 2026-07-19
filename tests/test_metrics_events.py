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


async def test_late_subscriber_to_a_finished_run_gets_run_complete_and_closes() -> None:
    """A dashboard tab opened (or refreshed) after a run has already fully
    completed must see that outcome immediately, not hang forever waiting
    for events that already went out to nobody."""
    bus = EventBus()
    bus.publish("run-1", {"type": "progress", "phase": "chaos"})
    bus.publish("run-1", {"type": "run_complete", "total_count": 10})

    events = [event async for event in bus.subscribe("run-1")]
    assert events == [{"type": "run_complete", "total_count": 10}]


async def test_late_subscriber_to_an_in_progress_run_gets_current_state_then_more() -> None:
    """Attaching mid-run should show the current snapshot immediately, then
    keep streaming, rather than showing nothing until the next tick."""
    bus = EventBus()
    bus.publish("run-1", {"type": "progress", "total_count": 5})

    async def collect() -> list[dict[str, object]]:
        return [event async for event in bus.subscribe("run-1")]

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.01)  # let the replay happen before publishing more
    bus.publish("run-1", {"type": "progress", "total_count": 12})
    bus.publish("run-1", {"type": "run_complete", "total_count": 20})

    events = await asyncio.wait_for(task, timeout=1.0)
    assert events == [
        {"type": "progress", "total_count": 5},
        {"type": "progress", "total_count": 12},
        {"type": "run_complete", "total_count": 20},
    ]


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
