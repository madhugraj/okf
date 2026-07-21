"""Learned embedding and reranking adapters for the independent RAG pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol, Sequence


DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_RERANKER_MODEL = "Qwen/Qwen3-Reranker-0.6B"
DEFAULT_EMBEDDING_DIMENSIONS = 1024
DEFAULT_RETRIEVAL_INSTRUCTION = (
    "Given a question about an approved website corpus, retrieve passages that answer it"
)


class DenseEncoder(Protocol):
    name: str
    dimensions: int
    minimum_similarity: float

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    name: str

    def score(self, question: str, documents: Sequence[str]) -> list[float]: ...


def normalize(vector: Sequence[float], *, dimensions: int) -> list[float]:
    values = [float(value) for value in vector[:dimensions]]
    if len(values) != dimensions or any(not math.isfinite(value) for value in values):
        raise ValueError(f"embedding must contain {dimensions} finite values")
    magnitude = math.sqrt(sum(value * value for value in values))
    if not magnitude:
        raise ValueError("embedding model returned a zero vector")
    return [value / magnitude for value in values]


@dataclass(slots=True)
class Qwen3EmbeddingEncoder:
    """Lazy SentenceTransformers adapter with query instructions and truncation."""

    model_name: str = DEFAULT_EMBEDDING_MODEL
    revision: str = "main"
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    device: str | None = None
    batch_size: int = 16
    instruction: str = DEFAULT_RETRIEVAL_INSTRUCTION
    minimum_similarity: float = 0.25
    _model: object | None = None

    @property
    def name(self) -> str:
        return f"{self.model_name}@{self.revision}/dimensions-{self.dimensions}"

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "Qwen embeddings require the 'models' extra: "
                    "python -m pip install -e '.[models]'"
                ) from exc
            options = {"trust_remote_code": True}
            if self.device and self.device != "auto":
                options["device"] = self.device
            self._model = SentenceTransformer(
                self.model_name, revision=self.revision, **options
            )
        return self._model

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        result = self._load().encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [normalize(vector, dimensions=self.dimensions) for vector in result]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        prompted = f"Instruct: {self.instruction}\nQuery: {text}"
        return self._encode([prompted])[0]


@dataclass(slots=True)
class Qwen3Reranker:
    """Lazy CrossEncoder adapter for the matching Qwen3 reranker family."""

    model_name: str = DEFAULT_RERANKER_MODEL
    revision: str = "main"
    device: str | None = None
    batch_size: int = 8
    _model: object | None = None

    @property
    def name(self) -> str:
        return f"{self.model_name}@{self.revision}"

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RuntimeError(
                    "Qwen reranking requires the 'models' extra: "
                    "python -m pip install -e '.[models]'"
                ) from exc
            options = {"trust_remote_code": True}
            if self.device and self.device != "auto":
                options["device"] = self.device
            self._model = CrossEncoder(
                self.model_name, revision=self.revision, **options
            )
        return self._model

    def score(self, question: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        values = self._load().predict(
            [(question, document) for document in documents],
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        scores = [float(value) for value in values]
        if len(scores) != len(documents) or any(not math.isfinite(value) for value in scores):
            raise ValueError("reranker returned invalid scores")
        return scores
