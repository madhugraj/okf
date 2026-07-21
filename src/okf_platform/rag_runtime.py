"""Runtime selection for local validation or Qwen3 plus pgvector production mode."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
import os

from .rag_models import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RERANKER_MODEL,
    DenseEncoder,
    Qwen3EmbeddingEncoder,
    Qwen3Reranker,
    Reranker,
)
from .vector_store import DenseVectorStore, PGVECTOR_DIMENSIONS, PgVectorStore


@dataclass(frozen=True, slots=True)
class RagRuntimeConfig:
    mode: str = "local"
    postgres_dsn: str | None = None
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_revision: str = "main"
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    reranker_model: str = DEFAULT_RERANKER_MODEL
    reranker_revision: str = "main"
    device: str = "auto"
    embedding_batch_size: int = 16
    reranker_batch_size: int = 8
    sparse_candidates: int = 40
    dense_candidates: int = 40
    rerank_candidates: int = 20
    final_passages: int = 8

    @classmethod
    def from_env(cls) -> RagRuntimeConfig:
        def number(name: str, default: int) -> int:
            try:
                value = int(os.getenv(name, str(default)))
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc
            if value < 1:
                raise ValueError(f"{name} must be positive")
            return value

        config = cls(
            mode=os.getenv("OKF_RAG_MODE", "local").strip().lower(),
            postgres_dsn=os.getenv("OKF_POSTGRES_DSN") or None,
            embedding_model=os.getenv("OKF_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
            embedding_revision=os.getenv("OKF_EMBEDDING_REVISION", "main"),
            embedding_dimensions=number(
                "OKF_EMBEDDING_DIMENSIONS", DEFAULT_EMBEDDING_DIMENSIONS
            ),
            reranker_model=os.getenv("OKF_RERANKER_MODEL", DEFAULT_RERANKER_MODEL),
            reranker_revision=os.getenv("OKF_RERANKER_REVISION", "main"),
            device=os.getenv("OKF_MODEL_DEVICE", "auto"),
            embedding_batch_size=number("OKF_EMBEDDING_BATCH_SIZE", 16),
            reranker_batch_size=number("OKF_RERANKER_BATCH_SIZE", 8),
            sparse_candidates=number("OKF_SPARSE_CANDIDATES", 40),
            dense_candidates=number("OKF_DENSE_CANDIDATES", 40),
            rerank_candidates=number("OKF_RERANK_CANDIDATES", 20),
            final_passages=number("OKF_FINAL_PASSAGES", 8),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode not in {"local", "production"}:
            raise ValueError("OKF_RAG_MODE must be 'local' or 'production'")
        if not self.embedding_revision.strip() or not self.reranker_revision.strip():
            raise ValueError("model revisions cannot be empty")
        if self.mode == "production":
            if not self.postgres_dsn:
                raise ValueError("OKF_POSTGRES_DSN is required in production RAG mode")
            if self.embedding_dimensions != PGVECTOR_DIMENSIONS:
                raise ValueError(
                    f"production pgvector schema requires {PGVECTOR_DIMENSIONS} dimensions"
                )
        if self.rerank_candidates > self.sparse_candidates + self.dense_candidates:
            raise ValueError("rerank candidate count exceeds the retrieval candidate pool")
        if self.final_passages > self.rerank_candidates:
            raise ValueError("final passage count cannot exceed rerank candidate count")

    def public_dict(self) -> dict[str, object]:
        missing_dependencies = []
        if self.mode == "production":
            for module in ("sentence_transformers", "psycopg", "pgvector"):
                if find_spec(module) is None:
                    missing_dependencies.append(module)
        return {
            "mode": self.mode,
            "vector_backend": (
                "postgresql-pgvector/hnsw-cosine/1.0"
                if self.mode == "production"
                else "local-json/1.0"
            ),
            "embedding_model": (
                f"{self.embedding_model}@{self.embedding_revision}"
                if self.mode == "production"
                else "feature-hash"
            ),
            "embedding_dimensions": (
                self.embedding_dimensions if self.mode == "production" else 256
            ),
            "reranker_model": (
                f"{self.reranker_model}@{self.reranker_revision}"
                if self.mode == "production"
                else "heuristic"
            ),
            "retrieval": {
                "sparse": "BM25",
                "dense_candidates": self.dense_candidates,
                "sparse_candidates": self.sparse_candidates,
                "fusion": "reciprocal-rank-fusion",
                "rerank_candidates": self.rerank_candidates,
                "final_passages": self.final_passages,
            },
            "ready": self.mode == "local" or (
                bool(self.postgres_dsn) and not missing_dependencies
            ),
            "missing_dependencies": missing_dependencies,
        }


@dataclass(slots=True)
class RagRuntime:
    config: RagRuntimeConfig
    encoder: DenseEncoder
    reranker: Reranker
    vector_store: DenseVectorStore | None


def create_rag_runtime(config: RagRuntimeConfig | None = None) -> RagRuntime:
    # Imports avoid a cycle while preserving a provider-free default install.
    from .rag import DEFAULT_ENCODER, DEFAULT_RERANKER

    config = config or RagRuntimeConfig.from_env()
    if config.mode == "local":
        return RagRuntime(config, DEFAULT_ENCODER, DEFAULT_RERANKER, None)
    encoder = Qwen3EmbeddingEncoder(
        model_name=config.embedding_model,
        revision=config.embedding_revision,
        dimensions=config.embedding_dimensions,
        device=config.device,
        batch_size=config.embedding_batch_size,
    )
    reranker = Qwen3Reranker(
        model_name=config.reranker_model,
        revision=config.reranker_revision,
        device=config.device,
        batch_size=config.reranker_batch_size,
    )
    return RagRuntime(config, encoder, reranker, PgVectorStore(config.postgres_dsn or ""))
