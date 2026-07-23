# ADR-0003: QA risk acceptance and Stage 2 input contract

## Status

Accepted for implementation.

## Decision

Coverage findings may be accepted by an identified human reviewer only when the finding code is on
the explicit waivable allowlist. This includes failure of a supplementary crawler-discovery tool,
because the remaining crawler and QA evidence can still be reviewed as a bounded corpus. The
reviewer must provide rationale and residual risk. Corpus integrity, storage, independent QA-tool
execution and stability failures cannot be waived.

Every approval creates a verified, immutable corpus snapshot. Stage 2 pipelines must use that
snapshot rather than crawler state or mutable local folders. The first Stage 2 derivative is a
deterministic typed-text extraction with source location and object-hash provenance.

## Consequences

- The original QA verdict remains preserved beside the effective human decision.
- Downstream results disclose accepted corpus limitations.
- Re-crawling cannot silently change an already approved Stage 2 input.
- Binary asset types remain visible even before OCR or transcription is configured.
- Later OKF and RAG experiments can be reproduced against the same snapshot hash.
