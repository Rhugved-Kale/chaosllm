from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from httpx import ASGITransport

import demo.llm_client as llm_client
from demo.main import app


@pytest.fixture(autouse=True)
def _reset_circuit_breaker() -> None:
    # The breaker is a module-level singleton so state persists across
    # requests within a process, by design (that's what makes it useful).
    # Reset it between tests so one test's failures can't leak into another.
    llm_client._breaker.record_success()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client
