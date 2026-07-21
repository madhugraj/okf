# Production Hybrid RAG

## What is implemented

The production pipeline is:

```text
question
  -> query decomposition
  -> BM25 top 40 + Qwen3/pgvector top 40
  -> Reciprocal Rank Fusion
  -> Qwen3 reranker top 20
  -> parent diversity and top 8 evidence passages
  -> exact citation verification
  -> grounded answer or abstention
```

The PostgreSQL table stores corpus ID, index version, embedding version, child and parent IDs,
source object, asset type, source URLs and a 1,024-dimensional vector. HNSW uses cosine distance.
Raw assets, Stage 2 records and citation text remain in the content-addressed local corpus; the
database is a derived search index and can be rebuilt.

The model adapters follow the official [Qwen3 embedding model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B),
[Qwen3 reranker model card](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B), and
[pgvector Python integration](https://github.com/pgvector/pgvector-python).

## Local Mac setup

Docker Desktop must be running. From the repository:

```bash
docker compose up -d postgres
source .venv/bin/activate
python -m pip install -e ".[dev,production-rag]"
export OKF_RAG_MODE=production
export OKF_POSTGRES_DSN='postgresql://okf:okf-local@127.0.0.1:5432/okf'
export OKF_MODEL_DEVICE=auto
okf-ui
```

The first RAG build downloads the Qwen3 models and embeds the approved corpus, so it is expected
to take longer than subsequent builds. The application creates the pgvector extension, schema,
tables and indexes on first use. The configured database user therefore needs permission to
create the `vector` extension; alternatively, a database administrator can apply
`src/okf_platform/sql/001_pgvector.sql` in advance.

Open the UI and confirm that **Retrieval Runtime** shows:

- `Production hybrid`;
- `postgresql-pgvector/hnsw-cosine/1.0`;
- `Qwen/Qwen3-Embedding-0.6B@<revision> · 1024D`; and
- `Qwen/Qwen3-Reranker-0.6B@<revision>`.

If it says **Local baseline**, the server was started without the production environment
variables. Stop `okf-ui`, export them in the same Terminal, and start it again.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `OKF_RAG_MODE` | `local` | Set to `production` for Qwen3 and pgvector |
| `OKF_POSTGRES_DSN` | — | PostgreSQL connection string; required in production mode |
| `OKF_EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-0.6B` | Learned embedding model |
| `OKF_EMBEDDING_REVISION` | `main` | Hugging Face revision; pin a commit SHA for research runs |
| `OKF_EMBEDDING_DIMENSIONS` | `1024` | Stored dimension; production schema requires 1,024 |
| `OKF_RERANKER_MODEL` | `Qwen/Qwen3-Reranker-0.6B` | Cross-encoder reranker |
| `OKF_RERANKER_REVISION` | `main` | Hugging Face revision; pin a commit SHA for research runs |
| `OKF_MODEL_DEVICE` | `auto` | SentenceTransformers device selection |
| `OKF_SPARSE_CANDIDATES` | `40` | BM25 candidates per decomposed query |
| `OKF_DENSE_CANDIDATES` | `40` | pgvector candidates per decomposed query |
| `OKF_RERANK_CANDIDATES` | `20` | Fused candidates scored by the reranker |
| `OKF_FINAL_PASSAGES` | `8` | Maximum parent-diverse evidence passages |

## Version and integrity rules

- An index manifest records the corpus and extraction hashes, embedding model, dimension, vector
  backend and chunk file hash.
- A model/dimension change uses a new artifact directory and database key.
- Research and production manifests should use immutable model commit SHAs rather than `main`.
- The critic reproduces every chunk from Stage 2 and checks the pgvector row count.
- Query citations are checked again against their exact parent offsets.
- pgvector is never treated as the source of truth; it is a rebuildable derivative.

## Evaluation

The common evaluation API now reports source-ranking Recall@5, Recall@10, MRR and nDCG@10 when
`expected_source_urls` are supplied, in addition to answer rate, abstention, citation validity,
expected-term recall and latency. Compare BM25-only, dense-only, hybrid and hybrid-plus-reranker
configurations on the same approved corpus and gold questions before selecting the final model.
