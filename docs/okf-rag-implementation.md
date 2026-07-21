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

The RAG workflow creates `advanced-rag/1.0` under:

```text
.okf-data/knowledge/<corpus-id>/advanced-rag-1.0/
  chunks.jsonl
  manifest.json
```

Retrieval combines BM25-style sparse ranking and deterministic dense feature hashing through reciprocal-rank fusion. It then applies query decomposition, metadata filtering, parent-level diversity, reranking, exact citation validation and an abstention rule.

The local feature hash and extractive answer generator are deliberately reproducible and provider-free. Both implement explicit adapter contracts. They are the functional baseline, not a claim of pretrained semantic or generative quality. A later approved provider can supply learned embeddings, reranking and answer generation while preserving the index and evidence contracts.

## UI and API

After Stage 2 completes, the UI exposes independent **Build OKF** and **Build RAG index** actions. Once both pass, a reviewer can ask one question and inspect both answers, timings and citations side by side.

API routes:

- `POST /api/corpora/{corpus_id}/okf/build`
- `POST /api/corpora/{corpus_id}/rag/build`
- `POST /api/corpora/{corpus_id}/compare`
- `POST /api/corpora/{corpus_id}/evaluate`

The evaluation API accepts questions plus optional expected terms, expected source URLs and RAG metadata filters. Research conclusions require a separately reviewed gold set.
