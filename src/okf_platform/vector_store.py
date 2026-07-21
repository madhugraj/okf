"""pgvector persistence for versioned RAG chunk embeddings."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Protocol, Sequence


PGVECTOR_DIMENSIONS = 1024


@dataclass(frozen=True, slots=True)
class DenseMatch:
    chunk_id: str
    score: float


class DenseVectorStore(Protocol):
    name: str

    def replace(
        self,
        corpus_id: str,
        index_version: str,
        embedding_version: str,
        chunks: Sequence[dict[str, object]],
        vectors: Sequence[Sequence[float]],
    ) -> None: ...

    def search(
        self,
        corpus_id: str,
        index_version: str,
        embedding_version: str,
        query_vector: Sequence[float],
        *,
        filters: dict[str, object] | None,
        limit: int,
    ) -> list[DenseMatch]: ...

    def count(self, corpus_id: str, index_version: str, embedding_version: str) -> int: ...


@dataclass(slots=True)
class PgVectorStore:
    dsn: str
    migration_path: Path | None = None
    name: str = "postgresql-pgvector/hnsw-cosine/1.0"
    _migrated: bool = False

    def _connect(self, *, register_type: bool = True):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "pgvector requires the 'postgres' extra: "
                "python -m pip install -e '.[postgres]'"
            ) from exc
        connection = psycopg.connect(self.dsn)
        if register_type:
            try:
                from pgvector.psycopg import register_vector
            except ImportError as exc:
                connection.close()
                raise RuntimeError(
                    "pgvector requires the 'postgres' extra: "
                    "python -m pip install -e '.[postgres]'"
                ) from exc
            register_vector(connection)
        return connection

    def migrate(self) -> None:
        if self._migrated:
            return
        path = self.migration_path or Path(__file__).with_name("sql") / "001_pgvector.sql"
        sql = path.read_text(encoding="utf-8")
        # The extension must exist before the Python vector type can be registered.
        with self._connect(register_type=False) as connection:
            for statement in (part.strip() for part in sql.split(";")):
                if statement:
                    connection.execute(statement)
        self._migrated = True

    @staticmethod
    def _validate_vectors(vectors: Sequence[Sequence[float]]) -> None:
        if any(len(vector) != PGVECTOR_DIMENSIONS for vector in vectors):
            raise ValueError(f"pgvector requires {PGVECTOR_DIMENSIONS}-dimensional embeddings")

    def replace(
        self,
        corpus_id: str,
        index_version: str,
        embedding_version: str,
        chunks: Sequence[dict[str, object]],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("every RAG chunk must have exactly one embedding")
        self._validate_vectors(vectors)
        self.migrate()
        rows = [
            (
                corpus_id,
                index_version,
                embedding_version,
                str(chunk["id"]),
                str(chunk["parent_id"]),
                str(chunk["unit_id"]),
                str(chunk["object_sha256"]),
                str(chunk["kind"]),
                json.dumps(chunk.get("source_urls", [])),
                vector,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        with self._connect() as connection:
            connection.execute(
                """DELETE FROM okf.rag_embeddings
                   WHERE corpus_id = %s AND index_version = %s AND embedding_version = %s""",
                (corpus_id, index_version, embedding_version),
            )
            connection.executemany(
                """INSERT INTO okf.rag_embeddings (
                       corpus_id, index_version, embedding_version, chunk_id, parent_id,
                       unit_id, object_sha256, kind, source_urls, embedding
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)""",
                rows,
            )

    def search(
        self,
        corpus_id: str,
        index_version: str,
        embedding_version: str,
        query_vector: Sequence[float],
        *,
        filters: dict[str, object] | None,
        limit: int,
    ) -> list[DenseMatch]:
        self._validate_vectors([query_vector])
        self.migrate()
        filters = filters or {}
        kind = filters.get("kind")
        source = str(filters.get("source_url_contains", "")).strip() or None
        pattern = f"%{source}%" if source else None
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT chunk_id, 1 - (embedding <=> %s) AS similarity
                   FROM okf.rag_embeddings
                   WHERE corpus_id = %s
                     AND index_version = %s
                     AND embedding_version = %s
                     AND (%s IS NULL OR kind = %s)
                     AND (%s IS NULL OR EXISTS (
                         SELECT 1
                         FROM jsonb_array_elements_text(source_urls) AS source(source_url)
                         WHERE source.source_url ILIKE %s
                     ))
                   ORDER BY embedding <=> %s
                   LIMIT %s""",
                (
                    query_vector,
                    corpus_id,
                    index_version,
                    embedding_version,
                    kind,
                    kind,
                    source,
                    pattern,
                    query_vector,
                    limit,
                ),
            ).fetchall()
        return [DenseMatch(str(chunk_id), float(score)) for chunk_id, score in rows]

    def count(self, corpus_id: str, index_version: str, embedding_version: str) -> int:
        self.migrate()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT count(*) FROM okf.rag_embeddings
                   WHERE corpus_id = %s AND index_version = %s AND embedding_version = %s""",
                (corpus_id, index_version, embedding_version),
            ).fetchone()
        return int(row[0])
