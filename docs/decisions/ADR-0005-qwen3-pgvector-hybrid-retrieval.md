# ADR-0005: Qwen3 and pgvector Hybrid Retrieval

## Status

Accepted for implementation.

## Context

The provider-free feature-hash index proved pipeline separation, provenance, critics and
evaluation, but it is not a learned semantic retriever. BM25 is valuable for names, acronyms,
numbers and exact phrases, but cannot reliably retrieve a passage expressed with different
vocabulary. Dense retrieval alone can lose exact lexical evidence.

## Decision

Production RAG uses:

- `Qwen/Qwen3-Embedding-0.6B`, truncated and normalized to 1,024 dimensions;
- PostgreSQL with pgvector and an HNSW cosine index;
- the existing BM25 child-chunk scorer as an independent lexical channel;
- Reciprocal Rank Fusion over the top 40 lexical and top 40 dense candidates;
- `Qwen/Qwen3-Reranker-0.6B` over the top 20 fused candidates;
- parent diversity and up to eight final evidence passages; and
- exact citation verification plus abstention when neither lexical nor dense evidence clears
  the grounding gate.

Every database row is keyed by corpus, index and embedding versions. Changing an embedding
model creates a separate local artifact and a separate pgvector partition; it does not silently
reuse incompatible vectors.

The RAG pipeline continues to read Stage 2 extraction only. It cannot read OKF claims. OKF and
RAG therefore remain independently comparable over the same frozen corpus.

## Consequences

- Semantic retrieval requires the optional model and PostgreSQL dependencies, model weights,
  and a running pgvector database.
- First build latency is materially higher because each child chunk must be embedded once.
- Query latency includes embedding and cross-encoder inference.
- The 1,024-dimension schema supports the selected 0.6B model and a future 4B benchmark at the
  same stored dimension.
- The local feature-hash path remains available for tests and environments that have not enabled
  production mode, and the UI identifies it clearly as a local baseline.
