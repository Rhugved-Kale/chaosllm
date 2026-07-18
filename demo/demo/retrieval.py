"""In-process retrieval over the demo corpus (DESIGN.md 4.6: "in-process
vector store (chromadb)").

Uses chromadb as the vector store, but with a small deterministic hashing
embedding function instead of chromadb's default sentence-transformer model.
That default downloads an ~80MB ONNX model from HuggingFace on first use,
which is a bad fit for a demo that needs to start fast and work offline and
in CI. Retrieval quality isn't the point here (this project tests
resilience under faults, not search relevance); what matters is that
retrieval is fast, deterministic, and never depends on the LLM or the proxy,
so it can't itself be affected by the faults this whole project injects.
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

_DIMENSIONS = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "of", "in", "on", "at", "to",
    "and", "or", "it", "its", "that", "this", "with", "as", "by", "be", "has",
    "have", "can", "for", "from", "into",
}  # fmt: skip


class HashingEmbeddingFunction(EmbeddingFunction[Documents]):  # type: ignore[misc]
    """Deterministic bag-of-words hashing embedding, L2-normalized."""

    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:
        return [_embed(text) for text in input]  # type: ignore[misc]

    @staticmethod
    def name() -> str:
        return "chaosllm-hashing"

    def get_config(self) -> dict[str, Any]:
        return {}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> HashingEmbeddingFunction:
        return HashingEmbeddingFunction()


def _embed(text: str) -> list[float]:
    vector = [0.0] * _DIMENSIONS
    for token in _TOKEN_RE.findall(text.lower()):
        if token in _STOPWORDS or len(token) < 2:
            continue
        bucket = int(hashlib.blake2b(token.encode(), digest_size=4).hexdigest(), 16) % _DIMENSIONS
        vector[bucket] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def build_collection(corpus: list[dict[str, str]]) -> Collection:
    # chromadb.EphemeralClient() instances share process-global state keyed
    # by settings, so a fixed collection name collides across repeated calls
    # in the same process (e.g. once per test). A unique name per call keeps
    # each build_collection() isolated; callers never need the name back.
    client = chromadb.EphemeralClient()
    collection = client.create_collection(
        name=f"chaosllm-demo-corpus-{uuid.uuid4().hex}",
        embedding_function=HashingEmbeddingFunction(),
    )
    collection.add(
        ids=[doc["id"] for doc in corpus],
        documents=[doc["text"] for doc in corpus],
    )
    return collection


def retrieve(collection: Collection, query: str, k: int = 3) -> list[dict[str, str]]:
    result = collection.query(query_texts=[query], n_results=k)
    ids = result["ids"][0]
    documents = result["documents"][0] if result["documents"] else []
    return [{"id": doc_id, "text": text} for doc_id, text in zip(ids, documents, strict=True)]
