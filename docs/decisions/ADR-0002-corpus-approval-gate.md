# ADR-0002: Human Approval Before Corpus Use

- Status: Proposed
- Date: 2026-07-21

## Context

OKF and RAG results cannot be compared fairly if they consume different, changing or insufficiently verified documents. A completed crawler run does not by itself prove that the corpus is ready.

## Decision

Introduce a mandatory human approval gate between Stage 1 discovery and all downstream parsing, OKF and RAG processing.

A run may be offered for approval only after its stopping rule passes. Approval freezes an immutable manifest containing document identities, hashes, provenance, exclusions, exceptions, policy snapshot and coverage evidence.

## Consequences

- Downstream systems reference a corpus version, never a mutable crawl workspace.
- Any added, removed or changed source document requires a new corpus version.
- Unresolved exceptions remain visible to the reviewer and in the manifest.
- Approval decisions require reviewer identity, timestamp and comment.
- Rejection or rerun returns the workflow to discovery/recovery without mutating a prior approved corpus.

## Validation

Automated tests must prove that:

1. transient URL states block readiness;
2. manifest validation failures block approval;
3. approval creates an immutable version;
4. downstream jobs reject unapproved run IDs; and
5. a later corpus version cannot alter an earlier manifest.
