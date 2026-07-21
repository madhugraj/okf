# Project Charter

## Purpose

Build an auditable platform that discovers document repositories within a website, allows a user to verify and approve the resulting corpus, and then compares Open Knowledge Format and advanced RAG over the exact same source material.

## Problem statement

Document-heavy websites commonly distribute PDFs across navigation pages, archive pages, pagination, sitemaps, JavaScript-rendered views, and direct storage URLs. A crawler that merely stops cannot demonstrate that it covered these surfaces. Downstream knowledge systems can therefore produce apparently strong results over an incomplete corpus.

This project makes corpus completeness evidence and human approval first-class gates.

## Objectives

1. Accept a public website URL and discover qualifying documents within the approved domain boundary.
2. Show crawl progress and exceptions in near real time.
3. Produce a reconciled inventory with source provenance, integrity evidence, duplicate groups and terminal status for every discovered URL.
4. Allow a user to approve an immutable, versioned corpus snapshot.
5. Transform the approved corpus into a defined Open Knowledge Format.
6. Build a separately configurable advanced RAG pipeline over the same corpus.
7. Evaluate both approaches with shared questions, evidence and reproducible metrics.

## Pilot scope

| Dimension | Decision |
|---|---|
| Pilot 1 | `https://www.aisats.in/` |
| Pilot 2 | `https://www.koltepatil.com/` |
| Archive meaning | Archive/history sections exposed by the target site |
| Initial document type | PDF; other formats require an explicit backlog decision |
| Orchestration | Python and LangGraph |
| Access model | Public, unauthenticated content only |
| Corpus gate | Explicit human approval |

AISATS is the initial controlled pilot. Kolte Patil is the second pilot used to test generalisation across a larger and more heterogeneous site structure.

## Non-goals for Stage 1

- Building OKF transformation or RAG retrieval
- Crawling external historical archives such as the Wayback Machine
- Circumventing authentication, anti-bot controls, paywalls or access restrictions
- Claiming knowledge of orphaned or undiscoverable URLs
- Using search-engine result counts as the sole proof of completeness
- Automatically approving a corpus

## Stakeholders

| Role | Responsibility |
|---|---|
| Product owner | Scope, prioritisation and corpus approval |
| Technical lead | Architecture, quality and delivery controls |
| Research lead | OKF/RAG experiment design and evaluation validity |
| Operator/reviewer | Crawl configuration, exception review and approval |
| Development team | Implementation, testing, observability and evidence |

## Success measures

### Stage 1

- 100% of discovered URLs have a terminal state.
- 100% of qualifying downloaded files have integrity metadata and provenance.
- 100% of failed or excluded items have a machine-readable reason.
- Repeated discovery converges according to the approved stopping rule.
- Archive coverage is reconciled by visible category, year and pagination path where available.
- A reviewer can inspect exceptions and approve or reject the corpus.

These measures prove coverage of observable discovery surfaces. They do not claim access to content the website does not expose.

### Comparative system

- OKF and RAG use the same corpus snapshot and evaluation set.
- Retrieval, grounding, citation, robustness, latency and cost metrics are reproducible.
- Each answer can be traced to source document and page-level evidence where parsing permits.

## Constraints and principles

- Respect robots directives, site terms, rate limits and applicable law.
- Prefer deterministic controls for crawling, validation and reconciliation; use agents for orchestration and bounded decisions.
- Preserve raw evidence and provenance before transformation.
- Make retries idempotent and resumable.
- Treat incomplete, blocked and ambiguous outcomes as visible states, not silent failures.
- No production credentials or personal data in the repository.

## Open decisions

1. Approve the formal OKF schema and validation rules.
2. Confirm the production object-storage endpoint and retention policy; local development uses the implemented content-addressed filesystem store.
3. Confirm the PostgreSQL deployment target for production metadata; local development uses SQLite.
4. Confirm model providers and data-handling constraints for later stages.
5. Select the expert process for gold-question and reference-answer creation.
6. Select a repository licence before external reuse or contribution.

## Milestone M0 exit criteria

- Charter, architecture and Stage 1 acceptance criteria reviewed
- Technology and pilot ADR accepted
- Corpus approval-gate ADR accepted
- Stage 1 backlog prioritised
- Open decisions assigned owners before they block implementation
