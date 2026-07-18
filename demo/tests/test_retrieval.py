from __future__ import annotations

from demo.corpus import CORPUS
from demo.retrieval import build_collection, retrieve


def test_retrieve_returns_k_documents_from_the_corpus() -> None:
    collection = build_collection(CORPUS)
    results = retrieve(collection, "tell me about oceans", k=3)
    assert len(results) == 3
    corpus_ids = {doc["id"] for doc in CORPUS}
    for result in results:
        assert result["id"] in corpus_ids
        assert result["text"]


def test_retrieve_is_deterministic() -> None:
    collection = build_collection(CORPUS)
    first = retrieve(collection, "the tallest mountain on Earth", k=3)
    second = retrieve(collection, "the tallest mountain on Earth", k=3)
    assert [d["id"] for d in first] == [d["id"] for d in second]
