# Stage 1 Plan: Auditable Document Discovery

## Outcome

A reviewer can submit one of the pilot website URLs, observe the crawl, inspect the reconciled document inventory and exceptions, rerun if needed, and approve an immutable corpus version.

## User journey

1. Create a crawl with target URL, allowed hosts, PDF filter, rate limit and resource budget.
2. Review the resolved policy before starting.
3. Watch pages and documents move through live states.
4. Inspect the inventory, source-page provenance, validation and duplicate groups.
5. Review coverage evidence and unresolved exceptions.
6. Rerun/recover or approve the corpus.
7. Receive a corpus version and manifest.

## Functional scope

### New Crawl

- Target URL and allowed-domain preview
- PDF-only initial filter
- Same-site archive inclusion
- Crawl depth, page, duration, concurrency and download-size budgets
- Robots and policy acknowledgement

### Live Crawl

- Run state and timestamps
- Pages queued, processed, failed and excluded
- Documents discovered, downloaded, validated and deduplicated
- Current activity and recent events
- Pause, resume and cancel
- Bounded retry status

### Document Inventory

- Search and filters by source path, status, MIME, year and duplicate group
- Original URL and referring page
- Filename, bytes, hash, page count and validation result
- Text/scanned classification when available
- Safe preview or download link
- Inclusion/exclusion review state

### Coverage and Approval

- Discovery-surface reconciliation
- Archive traversal evidence
- Failure and exclusion register
- Convergence result
- Readiness controls
- Rerun/recover action
- Approve/reject with comment
- Immutable corpus manifest

## Delivery increments

| Increment | Deliverable | Exit evidence |
|---|---|---|
| S1.1 Policy and seeds | URL safety, scope, sitemap and robots snapshot | Policy tests pass |
| S1.2 Static discovery | Link frontier, pagination and PDF discovery | Fixture recall passes |
| S1.3 Retrieval | Idempotent downloads, hashes, retries and provenance | Failure-injection tests pass |
| S1.4 Validation | PDF signature/parse checks and exact duplicates | Corrupt/duplicate fixtures pass |
| S1.5 Reconciliation | Coverage bundle and convergence rule | Synthetic-site oracle matches |
| S1.6 API and events | Run control, inventory API and event stream | Contract tests pass |
| S1.7 Frontend | Four Stage 1 screens | User acceptance walkthrough passes |
| S1.8 AISATS pilot | Site inventory and evidence report | Reviewer accepts or records gaps |
| S1.9 Kolte Patil pilot | Generalisation report and adapter rules | Reviewer accepts or records gaps |

## Test strategy

### Deterministic fixtures

Build local synthetic websites with known truth sets covering:

- sitemap-only PDFs;
- navigation and archive pagination;
- relative, absolute and redirected URLs;
- query-string duplicates and URL fragments;
- mislabeled MIME types;
- truncated and corrupt PDFs;
- exact and near duplicates;
- transient 429/5xx responses;
- access denied and missing resources;
- JavaScript-inserted links;
- redirect attempts outside the allowed domain;
- crawl cycles and infinite-calendar traps.

### Test levels

| Level | Purpose |
|---|---|
| Unit | URL rules, state transitions, hashing, retry classes and manifest validation |
| Contract | API, event schema, storage and graph-node interfaces |
| Integration | Crawler against deterministic fixture sites |
| Security | SSRF, unsafe redirect, resource exhaustion and untrusted-content handling |
| Pilot | Evidence review against AISATS and Kolte Patil public surfaces |
| Regression | Fixed discovery fixtures and approved pilot manifests where permissible |

## Stopping rule

A run may enter `awaiting_approval` only when:

1. the crawl frontier is empty;
2. no transient states remain;
3. every discovered URL has a terminal status;
4. all mandatory discovery surfaces have reconciliation records;
5. retry budgets are exhausted or failures resolved;
6. a second discovery pass produces no new qualifying canonical URLs; and
7. the coverage bundle and manifest validate.

The stopping rule does not auto-approve the corpus.

## Stage 1 definition of done

- All four user screens satisfy approved acceptance tests.
- AISATS and Kolte Patil runs complete without unclassified failures.
- Every qualifying document is downloaded or appears in the exception register.
- Raw evidence, metadata and audit events are reproducible from a run ID.
- Duplicate grouping does not remove provenance.
- Corpus approval produces a content-addressed manifest and immutable version.
- Security and resource-budget tests pass.
- Known limitations are documented with impact and mitigation.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| JavaScript hides links | Escalate specific pages to bounded Playwright rendering |
| Site changes during crawl | Record retrieval time and response metadata; support snapshot comparison |
| Infinite URL spaces | Canonicalisation, pattern controls and resource budgets |
| Rate limiting or blocking | Respectful rates, backoff and visible unresolved status |
| Orphan/unlinked documents | State the observable boundary; compare configured discovery surfaces |
| Duplicate URLs/content | Separate URL identity, content identity and logical document version |
| Prompt injection in documents | Treat content as untrusted data; agents cannot change policy from page text |
| False completeness claim | Evidence bundle, convergence rule and human approval |
