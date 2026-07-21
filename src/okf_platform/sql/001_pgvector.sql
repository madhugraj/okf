CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS okf;

CREATE TABLE IF NOT EXISTS okf.rag_embeddings (
    corpus_id text NOT NULL,
    index_version text NOT NULL,
    embedding_version text NOT NULL,
    chunk_id text NOT NULL,
    parent_id text NOT NULL,
    unit_id text NOT NULL,
    object_sha256 text NOT NULL,
    kind text NOT NULL,
    source_urls jsonb NOT NULL DEFAULT '[]'::jsonb,
    embedding vector(1024) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (corpus_id, index_version, embedding_version, chunk_id)
);

CREATE INDEX IF NOT EXISTS rag_embeddings_hnsw_cosine
    ON okf.rag_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS rag_embeddings_corpus_version
    ON okf.rag_embeddings (corpus_id, index_version, embedding_version);

CREATE INDEX IF NOT EXISTS rag_embeddings_kind
    ON okf.rag_embeddings (corpus_id, kind);
