from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType

import pytest

from okf_platform.rag_runtime import RagRuntimeConfig
from okf_platform.vector_store import PGVECTOR_DIMENSIONS, PgVectorStore


def test_production_runtime_requires_pgvector_dsn() -> None:
    with pytest.raises(ValueError, match="OKF_POSTGRES_DSN"):
        RagRuntimeConfig(mode="production").validate()


def test_production_runtime_requires_schema_dimension() -> None:
    with pytest.raises(ValueError, match=str(PGVECTOR_DIMENSIONS)):
        RagRuntimeConfig(
            mode="production", postgres_dsn="postgresql://example", embedding_dimensions=384
        ).validate()


def test_pgvector_migration_has_versioned_hnsw_cosine_index() -> None:
    from okf_platform import vector_store

    sql = (Path(vector_store.__file__).with_name("sql") / "001_pgvector.sql").read_text()
    assert "vector(1024)" in sql
    assert "USING hnsw" in sql
    assert "vector_cosine_ops" in sql
    assert "corpus_id" in sql
    assert "embedding_version" in sql


def test_pgvector_bootstrap_creates_extension_before_registering_type(
    tmp_path, monkeypatch
) -> None:
    events = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def close(self):
            events.append("close")

        def execute(self, sql, parameters=None):
            events.append(("execute", sql.strip(), parameters))
            return self

        def executemany(self, sql, rows):
            events.append(("executemany", sql.strip(), list(rows)))

    psycopg = ModuleType("psycopg")
    psycopg.connect = lambda dsn: events.append(("connect", dsn)) or FakeConnection()
    pgvector = ModuleType("pgvector")
    pgvector.__path__ = []
    pgvector_psycopg = ModuleType("pgvector.psycopg")
    pgvector_psycopg.register_vector = lambda connection: events.append("register_vector")
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    monkeypatch.setitem(sys.modules, "pgvector", pgvector)
    monkeypatch.setitem(sys.modules, "pgvector.psycopg", pgvector_psycopg)
    migration = tmp_path / "migration.sql"
    migration.write_text("CREATE EXTENSION IF NOT EXISTS vector;")
    store = PgVectorStore("postgresql://fixture", migration_path=migration)
    chunk = {
        "id": "chunk-1",
        "parent_id": "parent-1",
        "unit_id": "unit-1",
        "object_sha256": "a" * 64,
        "kind": "html",
        "source_urls": ["https://example.com/"],
    }

    store.replace(
        "corpus-1",
        "index-1",
        "embedding-1",
        [chunk],
        [[0.0] * PGVECTOR_DIMENSIONS],
    )

    extension_event = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, tuple) and "CREATE EXTENSION" in event[1]
    )
    assert extension_event < events.index("register_vector")
    assert any(isinstance(event, tuple) and event[0] == "executemany" for event in events)
