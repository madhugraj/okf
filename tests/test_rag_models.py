from __future__ import annotations

import sys
from types import ModuleType

from okf_platform.rag_models import Qwen3EmbeddingEncoder, Qwen3Reranker


def test_qwen_embedding_adapter_versions_normalizes_and_instructs_queries(monkeypatch) -> None:
    calls = {"loads": [], "texts": []}

    class FakeSentenceTransformer:
        def __init__(self, model_name, **options):
            calls["loads"].append((model_name, options))

        def encode(self, texts, **options):
            calls["texts"].append((list(texts), options))
            return [[3.0, 4.0, 12.0] for _ in texts]

    module = ModuleType("sentence_transformers")
    module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    encoder = Qwen3EmbeddingEncoder(
        model_name="fixture/embedding",
        revision="abc123",
        dimensions=2,
        instruction="retrieve approved evidence",
    )

    assert encoder.embed_documents(["document"])[0] == [0.6, 0.8]
    assert encoder.embed_query("question") == [0.6, 0.8]
    assert encoder.name == "fixture/embedding@abc123/dimensions-2"
    assert calls["loads"][0][1]["revision"] == "abc123"
    assert calls["texts"][1][0] == [
        "Instruct: retrieve approved evidence\nQuery: question"
    ]


def test_qwen_reranker_adapter_preserves_candidate_order(monkeypatch) -> None:
    calls = []

    class FakeCrossEncoder:
        def __init__(self, model_name, **options):
            calls.append(("load", model_name, options))

        def predict(self, pairs, **options):
            calls.append(("predict", list(pairs), options))
            return [0.2, 0.9]

    module = ModuleType("sentence_transformers")
    module.CrossEncoder = FakeCrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    reranker = Qwen3Reranker(model_name="fixture/reranker", revision="def456")

    assert reranker.score("question", ["first", "second"]) == [0.2, 0.9]
    assert reranker.name == "fixture/reranker@def456"
    assert calls[0][2]["revision"] == "def456"
    assert calls[1][1] == [("question", "first"), ("question", "second")]
