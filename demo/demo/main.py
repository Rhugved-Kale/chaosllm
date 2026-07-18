"""FastAPI demo RAG app: POST /ask -> retrieve -> LLM -> {answer, citations}.

RESILIENT=true|false (env var) selects the naive or resilient LLM call path
(DESIGN.md 4.6). PROXY_BASE_URL points the LLM call at the chaosllm proxy
instead of the real provider; that's the app's one required change to be
chaos-testable.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from demo.corpus import CORPUS
from demo.llm_client import LLMUnavailableError, naive_ask_llm, resilient_ask_llm
from demo.retrieval import build_collection, retrieve

PROXY_BASE_URL = os.environ.get("PROXY_BASE_URL", "http://127.0.0.1:8000")


def _resilient_mode() -> bool:
    # Read per-call rather than as a module constant: makes RESILIENT
    # flippable in tests via monkeypatch without fighting import order.
    return os.environ.get("RESILIENT", "false").lower() == "true"


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    citations: list[str]
    degraded: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.collection = build_collection(CORPUS)
    app.state.llm_client = httpx.AsyncClient(base_url=PROXY_BASE_URL)
    yield
    await app.state.llm_client.aclose()


app = FastAPI(title="chaosllm-demo", lifespan=lifespan)


@app.post("/ask", response_model=AskResponse)
async def ask(payload: AskRequest) -> AskResponse:
    docs = retrieve(app.state.collection, payload.question, k=3)
    context = "\n".join(doc["text"] for doc in docs)
    citations = [doc["id"] for doc in docs]

    if not _resilient_mode():
        answer = await naive_ask_llm(app.state.llm_client, payload.question, context)
        return AskResponse(answer=answer, citations=citations)

    try:
        answer = await resilient_ask_llm(app.state.llm_client, payload.question, context)
        return AskResponse(answer=answer, citations=citations)
    except LLMUnavailableError:
        extractive_answer = docs[0]["text"] if docs else ""
        return AskResponse(answer=extractive_answer, citations=citations, degraded=True)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}
