# OKF and Advanced RAG Implementation

## Shared input contract

Both pipelines start from the approved corpus snapshot and `typed-extraction/1.0` records. Each load rechecks the extraction-record hash. Raw corpus files remain immutable.

## OKF Builder Agent

The OKF workflow creates `open-knowledge-format/1.0` under:

```text
.okf-data/knowledge/<corpus-id>/open-knowledge-format-1.0/
  bundle.json
  manifest.json
```

The bundle contains documents, canonical entities, concepts, atomic claims, entity relationships, temporal mentions, possible conflicts, and exact evidence quotes. Runtime validation rejects duplicate IDs, missing extraction units and any quote whose character offsets do not reproduce the source text.

## Advanced RAG Agent

The RAG workflow creates a model-versioned `advanced-rag/1.1` artifact under:

```text
.okf-data/knowledge/<corpus-id>/advanced-rag-1.1/
  embedding-<model-hash>/
    chunks.jsonl
    manifest.json
```

Retrieval combines BM25 sparse ranking and learned Qwen3 dense retrieval from pgvector through reciprocal-rank fusion. It then applies query decomposition, metadata filtering, parent-level diversity, Qwen3 cross-encoder reranking, exact citation validation and an abstention rule.

The local feature hash remains a reproducible, provider-free validation mode. Production mode uses `Qwen/Qwen3-Embedding-0.6B` at 1,024 dimensions, PostgreSQL/pgvector HNSW cosine search and `Qwen/Qwen3-Reranker-0.6B`. The extractive answer generator remains deliberately grounded and provider-free; a later approved answer model can use the same retrieved evidence and citation contract.

Each embedding model and dimension has its own artifact directory and database key. The critic verifies every child span against Stage 2 and checks that pgvector contains exactly one embedding row for every frozen chunk.

## UI and API

After Stage 2 completes, the UI exposes independent **Build OKF** and **Build RAG index** actions. Once both pass, a reviewer can ask one question and inspect both answers, timings and citations side by side.

API routes:

- `POST /api/corpora/{corpus_id}/okf/build`
- `POST /api/corpora/{corpus_id}/rag/build`
- `POST /api/corpora/{corpus_id}/compare`
- `POST /api/corpora/{corpus_id}/evaluate`

The evaluation API accepts questions plus optional expected terms, expected source URLs and RAG metadata filters. When expected sources are supplied it reports Recall@5, Recall@10, MRR and nDCG@10, alongside citation, answer, abstention and latency metrics. Research conclusions require a separately reviewed gold set.
