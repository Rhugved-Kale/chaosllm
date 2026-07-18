"""ASGI reverse proxy: forwards /openai, /anthropic, and configured passthrough
routes to their real upstreams, unmodified, logging every request to the
metrics tap. Fault injection (DESIGN.md 4.2) lands in Phase 2.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from chaosllm.metrics.tap import MetricsTap, RequestRecord, now_iso
from chaosllm.proxy.config import ProxyConfig

OPENAI_BASE_URL = "https://api.openai.com"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"

# Hop-by-hop headers per RFC 7230 6.1, stripped in both directions. Also drops
# content-length: httpx recomputes it for the outbound request from the body
# we send, and the inbound value may not match once headers are re-emitted
# through StreamingResponse.
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
) -> FastAPI:
    """Build the proxy ASGI app.

    config/metrics_path/client are constructor parameters rather than globals
    or env reads so tests can build one isolated app per respx mock and per
    metrics file, with no shared state between tests.
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

    async def _proxy(
        request: Request, upstream_base: str, upstream_path: str, route_label: str
    ) -> Response:
        http_client: httpx.AsyncClient = app.state.client
        metrics: MetricsTap = app.state.metrics
        request_id = str(uuid.uuid4())

        upstream_url = f"{upstream_base.rstrip('/')}/{upstream_path.lstrip('/')}"
        if request.url.query:
            upstream_url = f"{upstream_url}?{request.url.query}"

        body = await request.body()
        headers = _filtered_headers(request.headers)

        start = time.perf_counter()
        upstream_request = http_client.build_request(
            request.method, upstream_url, headers=headers, content=body
        )
        upstream_response = await http_client.send(upstream_request, stream=True)
        latency_ms = (time.perf_counter() - start) * 1000

        response_headers = _filtered_headers(upstream_response.headers)
        response_headers["x-chaosllm-request-id"] = request_id

        async def body_iterator() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream_response.aiter_raw():
                    yield chunk
            finally:
                await upstream_response.aclose()

        await metrics.record(
            RequestRecord(
                request_id=request_id,
                timestamp=now_iso(),
                method=request.method,
                route=route_label,
                upstream=upstream_url,
                status=upstream_response.status_code,
                latency_ms=latency_ms,
            )
        )

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
