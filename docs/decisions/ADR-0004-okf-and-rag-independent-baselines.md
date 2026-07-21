# ADR-0004: Independent OKF and RAG Baselines

## Status

Accepted for the local pilot baseline.

## Decision

OKF and Advanced RAG consume the same frozen corpus snapshot and the same integrity-checked Stage 2 extraction, but run as separate LangGraph workflows and persist separate derivatives.

- OKF 1.0 uses canonical JSON, stable hash-derived IDs, evidence-linked atomic claims, entities, concepts, relationships, temporal mentions and potential-conflict records.
- RAG 1.0 uses child chunks with parent expansion, BM25-style sparse ranking, deterministic dense feature hashing, reciprocal-rank fusion, query decomposition, metadata filtering, reranking, exact citation validation and abstention.
- The common evaluator runs identical questions against both and records citations, answer state and latency.

## Rationale

Independent derivatives prevent one approach from gaining hidden knowledge from the other. A provider-free deterministic baseline makes local execution reproducible and establishes the contracts required for later learned embedding, reranker and answer-model adapters.

## Consequences

The current dense vector is a deterministic feature-hash representation, not a pretrained semantic embedding. It is suitable for engineering validation but must not be represented as the final research-quality semantic retriever. Pilot conclusions require a versioned learned-embedding adapter, a gold evaluation set and reviewed model/data-handling constraints.
