"""ASGI reverse proxy: forwards /openai, /anthropic, and configured passthrough
routes to their real upstreams, running every request through the fault
pipeline (DESIGN.md 4.2) first, and logging every request to the metrics tap.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from chaosllm.faults.pipeline import FaultPipeline
from chaosllm.metrics.tap import MetricsTap, RequestRecord, now_iso
from chaosllm.proxy.config import ProxyConfig
from chaosllm.proxy.control import router as control_router

OPENAI_BASE_URL = "https://api.openai.com"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"

# Hop-by-hop headers per RFC 7230 6.1, stripped in both directions. Also drops
# content-length: httpx recomputes it for the outbound request from the body
# we send, and the inbound value may not match once headers are re-emitted
# through StreamingResponse or after a fault mutates the body.
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
}


def _filtered_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}


def create_app(
    *,
    config: ProxyConfig | None = None,
    metrics_path: Path | None = None,
    client: httpx.AsyncClient | None = None,
    fault_pipeline: FaultPipeline | None = None,
) -> FastAPI:
    """Build the proxy ASGI app.

    config/metrics_path/client/fault_pipeline are constructor parameters
    rather than globals or env reads so tests can build one isolated app per
    respx mock, metrics file, and fault set, with no shared state between
    tests.
    """
    owns_client = client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if owns_client:
            await app.state.client.aclose()

    app = FastAPI(title="chaosllm-proxy", lifespan=lifespan)
    app.state.config = config or ProxyConfig()
    app.state.metrics = MetricsTap(metrics_path or Path("metrics.jsonl"))
    app.state.client = client or httpx.AsyncClient()
    app.state.fault_pipeline = fault_pipeline or FaultPipeline()
    app.include_router(control_router)

    async def _proxy(
        request: Request, upstream_base: str, upstream_path: str, route_label: str
    ) -> Response:
        request_received_at = time.perf_counter()
        http_client: httpx.AsyncClient = app.state.client
        metrics: MetricsTap = app.state.metrics
        pipeline: FaultPipeline = app.state.fault_pipeline
        request_id = str(uuid.uuid4())

        upstream_url = f"{upstream_base.rstrip('/')}/{upstream_path.lstrip('/')}"
        if request.url.query:
            upstream_url = f"{upstream_url}?{request.url.query}"

        body = await request.body()
        outcome = await pipeline.evaluate(request.url.path, body)
        body = outcome.request_body
        injected_delay_ms = outcome.pre_delay_s * 1000

        if outcome.pre_delay_s > 0:
            await asyncio.sleep(outcome.pre_delay_s)

        if outcome.short_circuit is not None:
            outcome.short_circuit.headers["x-chaosllm-request-id"] = request_id
            total_ms = (time.perf_counter() - request_received_at) * 1000
            await metrics.record(
                RequestRecord(
                    request_id=request_id,
                    timestamp=now_iso(),
                    method=request.method,
                    route=route_label,
                    upstream=upstream_url,
                    status=outcome.short_circuit.status_code,
                    total_ms=total_ms,
                    upstream_ms=None,
                    injected_delay_ms=injected_delay_ms,
                    faults_fired=outcome.fired,
                )
            )
            return outcome.short_circuit

        headers = _filtered_headers(request.headers)

        upstream_start = time.perf_counter()
        upstream_request = http_client.build_request(
            request.method, upstream_url, headers=headers, content=body
        )
        upstream_response = await http_client.send(upstream_request, stream=True)
        upstream_ms = (time.perf_counter() - upstream_start) * 1000

        response_headers = _filtered_headers(upstream_response.headers)
        response_headers["x-chaosllm-request-id"] = request_id

        if outcome.response_transform is not None:
            # truncate/malformed_json need the full body in hand, so this
            # path buffers instead of streaming. DESIGN.md 4.2 non-goals:
            # no streaming fault injection in v0.1, only the untouched
            # passthrough path below streams.
            raw_body = await upstream_response.aread()
            await upstream_response.aclose()
            transformed = outcome.response_transform.apply(raw_body)
            total_ms = (time.perf_counter() - request_received_at) * 1000
            await metrics.record(
                RequestRecord(
                    request_id=request_id,
                    timestamp=now_iso(),
                    method=request.method,
                    route=route_label,
                    upstream=upstream_url,
                    status=upstream_response.status_code,
                    total_ms=total_ms,
                    upstream_ms=upstream_ms,
                    injected_delay_ms=injected_delay_ms,
                    faults_fired=outcome.fired,
                )
            )
            return Response(
                content=transformed,
                status_code=upstream_response.status_code,
                headers=response_headers,
                media_type=upstream_response.headers.get("content-type"),
            )

        total_ms = (time.perf_counter() - request_received_at) * 1000
        await metrics.record(
            RequestRecord(
                request_id=request_id,
                timestamp=now_iso(),
                method=request.method,
                route=route_label,
                upstream=upstream_url,
                status=upstream_response.status_code,
                total_ms=total_ms,
                upstream_ms=upstream_ms,
                injected_delay_ms=injected_delay_ms,
                faults_fired=outcome.fired,
            )
        )

        async def body_iterator() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream_response.aiter_raw():
                    yield chunk
            finally:
                await upstream_response.aclose()

        return StreamingResponse(
            body_iterator(),
            status_code=upstream_response.status_code,
            headers=response_headers,
            media_type=upstream_response.headers.get("content-type"),
        )

    @app.api_route("/openai/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def openai_passthrough(path: str, request: Request) -> Response:
        return await _proxy(request, OPENAI_BASE_URL, path, "/openai")

    @app.api_route("/anthropic/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def anthropic_passthrough(path: str, request: Request) -> Response:
        return await _proxy(request, ANTHROPIC_BASE_URL, path, "/anthropic")

    @app.api_route(
        "/passthrough/{target_id}/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def generic_passthrough(target_id: str, path: str, request: Request) -> Response:
        proxy_config: ProxyConfig = app.state.config
        target = proxy_config.passthrough.get(target_id)
        if target is None:
            return Response(
                status_code=404,
                content=f"unknown passthrough target: {target_id}",
            )
        return await _proxy(request, target.base_url, path, f"/passthrough/{target_id}")

    return app
