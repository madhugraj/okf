# Stage 2: Approved-corpus knowledge preparation

## Goal

Transform one immutable, human-approved corpus snapshot into deterministic, source-linked text
units that can safely feed the Open Knowledge Format pipeline. Stage 2 never reads a live crawl
report as its source of truth and never changes raw corpus bytes.

## Increment 1 contract

1. An approval freezes a manifest of unique objects and every URL/referrer observation.
2. The freezer re-reads each local object and verifies its SHA-256 before accepting it.
3. Stage 2 reads only the versioned snapshot manifest.
4. PDF output retains page numbers; other text output retains character offsets and source URLs.
5. HTML scripts/styles are excluded from visible-text extraction.
6. Code, structured data and OpenXML Office files have explicit adapters.
7. Images, video, audio, archives and unsupported binaries receive a typed `not_extractable`
   outcome until an OCR/transcription/archive adapter is approved.
8. Extraction records and their manifest are content-hashed and idempotent.

## Human QA exceptions

A reviewer may accept `DISCOVERY_TOOL_FAILED`, `QA_ONLY_URLS` or `UNRESOLVED_BASELINE` findings
when the gap does not prevent the intended use. The exception is bound to the exact critic finding
and stores reviewer, timestamp, rationale, affected URLs and residual risk. Independent QA-tool
failure, missing corpus bytes, empty corpus, exhausted budget, incomplete processing and failed
stability remain hard gates.

An accepted exception changes the effective verdict to `accepted_with_exceptions`; it never rewrites
the original QA verdict.

## Stored outputs

```text
.okf-data/
  corpora/<corpus-id>/manifest.json
  stage2/<corpus-id>/typed-extraction-1.0/
    records.jsonl
    manifest.json
```

## Next increments

- OCR adapter and page-image evidence for scanned PDFs and images
- audio/video transcription adapters with time-code provenance
- archive expansion policy and malware-scan boundary
- approved OKF JSON schema, identifiers and validation
- bounded entity, concept, claim and relationship extraction
- human review for low-confidence or conflicting knowledge records
- common OKF versus RAG evaluation set over the same corpus snapshot
