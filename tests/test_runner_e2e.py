"""End-to-end: the real runner driving a stand-in target app through the real
proxy, LLM upstream mocked via respx. One test exercises phases, control API
toggling, SQLite persistence, and report rendering together.

Both the proxy and the stand-in target app run as real uvicorn servers on
loopback (not ASGI-transport-in-process) so the runner's own httpx clients,
which speak real HTTP to `spec.target.base_url` and `proxy_url`, are exercised
exactly as they would be against a real deployment.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import uvicorn
from fastapi import FastAPI, Request

from chaosllm.metrics.store import MetricsStore
from chaosllm.proxy.app import create_app
from chaosllm.report.render import render_markdown
from chaosllm.runner.runner import run_experiment


def test_run_experiment_has_no_metrics_file_path_parameter() -> None:
    """Regression guard: the runner must never again assume file-path access
    to the proxy's metrics.jsonl (see query_fault_fire_counts). That
    assumption is exactly what silently zeroed every fault tally the moment
    the proxy ran in a different process/container than the runner.
    """
    params = inspect.signature(run_experiment).parameters
    assert "proxy_metrics_path" not in params


@asynccontextmanager
async def _serve(app: FastAPI) -> AsyncIterator[str]:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


def _build_target_app(proxy_url: str) -> FastAPI:
    """A minimal naive RAG-shaped target: no timeout override, no fallback.

    Deliberately propagates a proxy-side error as its own 500 (matching
    DESIGN.md 4.6's RESILIENT=false path), so a chaos-phase error fault shows
    up as a runner-visible failure and exercises the success_rate assertion.
    """
    target_app = FastAPI()

    @target_app.post("/ask")
    async def ask(request: Request) -> dict[str, Any]:
        payload = await request.json()
        async with httpx.AsyncClient(base_url=proxy_url, timeout=5.0) as client:
            resp = await client.post(
                "/openai/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": payload["question"]}],
                },
            )
        resp.raise_for_status()
        body = resp.json()
        text = body["choices"][0]["message"]["content"]
        return {"answer": text, "citations": ["doc-1"]}

    return target_app


async def test_full_experiment_against_stand_in_target_app(tmp_path: Path) -> None:
    proxy_metrics_path = tmp_path / "proxy_metrics.jsonl"
    proxy_app = create_app(metrics_path=proxy_metrics_path)

    async with _serve(proxy_app) as proxy_url:
        target_app = _build_target_app(proxy_url)
        async with _serve(target_app) as target_url:
            payload_file = tmp_path / "questions.jsonl"
            payload_file.write_text('{"question": "What is chaos engineering?"}\n')

            spec_path = tmp_path / "spec.yaml"
            spec_path.write_text(
                f"""\
name: e2e-test
target:
  base_url: {target_url}
  endpoint: POST /ask
  payload_file: {payload_file}
load:
  concurrency: 2
  duration_s: 0.3
  warmup_s: 0.2
faults:
  - id: error
    status: 500
    route: /openai/*
    p: 1.0
assertions:
  - type: success_rate
    min: 0.5
"""
            )

            with respx.mock(assert_all_called=False) as router:
                # Loopback traffic (runner -> target app -> proxy -> control
                # API) is real HTTP between real servers in this process;
                # only the proxy's outbound call to the LLM provider is
                # mocked. assert_all_mocked=False would silently auto-mock
                # *all* unmatched requests (including the loopback ones)
                # with an empty 200 instead of letting them through, so mark
                # loopback explicitly pass-through instead.
                router.route(host="127.0.0.1").pass_through()
                router.post("https://api.openai.com/v1/chat/completions").mock(
                    return_value=httpx.Response(
                        200,
                        json={"choices": [{"message": {"content": "chaos engineering is..."}}]},
                    )
                )

                db_path = tmp_path / "chaosllm.db"
                summary = await run_experiment(
                    spec_path,
                    proxy_url=proxy_url,
                    db_path=db_path,
                    runs_dir=tmp_path / "runs",
                    request_timeout_s=2.0,
                )

    by_phase = {s.phase: s for s in summary.phase_summaries}

    assert by_phase["warmup"].total_count > 0
    assert by_phase["warmup"].success_count == by_phase["warmup"].total_count

    assert by_phase["chaos"].total_count > 0
    assert by_phase["chaos"].success_count == 0
    assert by_phase["chaos"].error_taxonomy.get("http_500", 0) == by_phase["chaos"].total_count

    assert by_phase["recovery"].total_count > 0
    assert by_phase["recovery"].success_count == by_phase["recovery"].total_count

    assert summary.fault_fire_counts.get("error", 0) > 0
    assert summary.assertion_results[0].passed is False

    # The fault actually fired during chaos, so this is a valid run: no
    # warnings, and warmup/recovery (faults off) fired nothing.
    assert summary.warnings == []
    assert by_phase["chaos"].fault_fire_counts.get("error", 0) > 0
    assert by_phase["warmup"].fault_fire_counts == {}
    assert by_phase["recovery"].fault_fire_counts == {}

    store = MetricsStore(db_path)
    try:
        markdown = render_markdown(store, summary.run_id)
        run = store.get_run(summary.run_id)
    finally:
        store.close()

    assert run is not None
    assert run.status == "completed"
    assert "Resilience report: e2e-test" in markdown
    assert "Success rate dropped" in markdown
    assert "[FAIL] `success_rate`" in markdown
    assert "<svg" in markdown
    assert "## Warnings" not in markdown


async def test_invalid_run_when_chaos_fault_route_never_carries_traffic(tmp_path: Path) -> None:
    """The vector-db-slow.yaml bug: a fault configured on a route the target
    app never calls fires zero times all experiment long. That's not a
    passing resilience result, it's a broken experiment, and the run must
    say so.
    """
    proxy_metrics_path = tmp_path / "proxy_metrics.jsonl"
    proxy_app = create_app(metrics_path=proxy_metrics_path)

    async with _serve(proxy_app) as proxy_url:
        target_app = _build_target_app(proxy_url)
        async with _serve(target_app) as target_url:
            payload_file = tmp_path / "questions.jsonl"
            payload_file.write_text('{"question": "What is chaos engineering?"}\n')

            spec_path = tmp_path / "spec.yaml"
            spec_path.write_text(
                f"""\
name: vacuous-fault-test
target:
  base_url: {target_url}
  endpoint: POST /ask
  payload_file: {payload_file}
load:
  concurrency: 1
  duration_s: 0.2
  warmup_s: 0.1
faults:
  - id: latency
    route: /passthrough/vectordb/*
    delay_ms: 100
    p: 1.0
assertions:
  - type: success_rate
    min: 0.5
"""
            )

            with respx.mock(assert_all_called=False) as router:
                router.route(host="127.0.0.1").pass_through()
                router.post("https://api.openai.com/v1/chat/completions").mock(
                    return_value=httpx.Response(
                        200, json={"choices": [{"message": {"content": "an answer"}}]}
                    )
                )

                db_path = tmp_path / "chaosllm.db"
                summary = await run_experiment(
                    spec_path,
                    proxy_url=proxy_url,
                    db_path=db_path,
                    runs_dir=tmp_path / "runs",
                    request_timeout_s=2.0,
                )

    assert summary.fault_fire_counts == {}
    assert summary.warnings != []
    assert "zero faults" in summary.warnings[0]

    store = MetricsStore(db_path)
    try:
        run = store.get_run(summary.run_id)
        markdown = render_markdown(store, summary.run_id)
    finally:
        store.close()

    assert run is not None
    assert run.status == "invalid"
    assert run.warnings == summary.warnings
    assert "## Warnings" in markdown


async def test_run_experiment_posts_completion_to_the_control_api(tmp_path: Path) -> None:
    """The runner's final run_complete POST actually reaches the proxy's
    control API and updates its live-run state (DESIGN.md 4.7's dashboard
    reads this), not just gets swallowed by a bug in the plumbing between
    them. The SSE fan-out itself is covered separately in
    test_control_events_api.py; this just proves the runner side calls it.
    """
    proxy_metrics_path = tmp_path / "proxy_metrics.jsonl"
    proxy_app = create_app(metrics_path=proxy_metrics_path)

    async with _serve(proxy_app) as proxy_url:
        target_app = _build_target_app(proxy_url)
        async with _serve(target_app) as target_url:
            payload_file = tmp_path / "questions.jsonl"
            payload_file.write_text('{"question": "What is chaos engineering?"}\n')

            spec_path = tmp_path / "spec.yaml"
            spec_path.write_text(
                f"""\
name: sse-wiring-test
target:
  base_url: {target_url}
  endpoint: POST /ask
  payload_file: {payload_file}
load:
  concurrency: 1
  duration_s: 0.1
  warmup_s: 0.1
assertions:
  - type: success_rate
    min: 0.5
"""
            )

            with respx.mock(assert_all_called=False) as router:
                router.route(host="127.0.0.1").pass_through()
                router.post("https://api.openai.com/v1/chat/completions").mock(
                    return_value=httpx.Response(
                        200, json={"choices": [{"message": {"content": "ok"}}]}
                    )
                )

                db_path = tmp_path / "chaosllm.db"
                summary = await run_experiment(
                    spec_path,
                    proxy_url=proxy_url,
                    db_path=db_path,
                    runs_dir=tmp_path / "runs",
                    request_timeout_s=2.0,
                )

        async with httpx.AsyncClient(base_url=proxy_url) as client:
            latest = await client.get("/control/runs/latest")
            assert latest.json() == {"run_id": summary.run_id}


async def test_run_complete_event_reports_the_chaos_phase_p95_latency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run_complete event used to carry no latency_p95_ms at all, so the
    dashboard's headline p95 number just kept showing whatever phase's live
    progress tick had last fired (recovery, since it runs last), silently
    mismatching the chaos-phase latency_p95_ms assertion shown right next to
    it. The event's p95 must match the chaos phase's own persisted summary.

    PROGRESS_INTERVAL_S is patched way down so at least one progress event
    (any event at all publishes the run_id via /control/runs/latest) fires
    well before run_complete, giving the SSE consumer below a real chance to
    discover the run_id and subscribe before the single run_complete publish
    it's actually asserting on. Otherwise, with the suite's usual sub-second
    phase durations, a run this short can complete and publish before an
    only-just-scheduled subscriber ever attaches, since the event bus has no
    replay for late subscribers.
    """
    monkeypatch.setattr("chaosllm.runner.runner.PROGRESS_INTERVAL_S", 0.02)
    proxy_metrics_path = tmp_path / "proxy_metrics.jsonl"
    proxy_app = create_app(metrics_path=proxy_metrics_path)

    async with _serve(proxy_app) as proxy_url:
        target_app = _build_target_app(proxy_url)
        async with _serve(target_app) as target_url:
            payload_file = tmp_path / "questions.jsonl"
            payload_file.write_text('{"question": "What is chaos engineering?"}\n')

            spec_path = tmp_path / "spec.yaml"
            spec_path.write_text(
                f"""\
name: p95-event-test
target:
  base_url: {target_url}
  endpoint: POST /ask
  payload_file: {payload_file}
load:
  concurrency: 1
  duration_s: 0.1
  warmup_s: 0.1
assertions:
  - type: success_rate
    min: 0.5
"""
            )

            with respx.mock(assert_all_called=False) as router:
                router.route(host="127.0.0.1").pass_through()
                router.post("https://api.openai.com/v1/chat/completions").mock(
                    return_value=httpx.Response(
                        200, json={"choices": [{"message": {"content": "ok"}}]}
                    )
                )

                received: list[dict[str, Any]] = []

                async def consume_run_complete(client: httpx.AsyncClient) -> None:
                    run_id = None
                    while run_id is None:
                        latest = await client.get("/control/runs/latest")
                        run_id = latest.json()["run_id"]
                        if run_id is None:
                            await asyncio.sleep(0.01)
                    async with client.stream("GET", f"/control/runs/{run_id}/events") as resp:
                        async for line in resp.aiter_lines():
                            if line.startswith("data: "):
                                received.append(json.loads(line[len("data: ") :]))
                                if received[-1].get("type") == "run_complete":
                                    return

                async with httpx.AsyncClient(base_url=proxy_url) as client:
                    consumer = asyncio.create_task(consume_run_complete(client))

                    db_path = tmp_path / "chaosllm.db"
                    summary = await run_experiment(
                        spec_path,
                        proxy_url=proxy_url,
                        db_path=db_path,
                        runs_dir=tmp_path / "runs",
                        request_timeout_s=2.0,
                    )
                    await asyncio.wait_for(consumer, timeout=2.0)

    store = MetricsStore(db_path)
    try:
        chaos_summary = next(
            s for s in store.get_phase_summaries(summary.run_id) if s.phase == "chaos"
        )
    finally:
        store.close()

    assert received[-1]["latency_p95_ms"] == chaos_summary.latency_p95_ms
