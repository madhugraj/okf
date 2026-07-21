# Stage 1 Backlog

## Prioritisation

- **P0** blocks a trustworthy pilot.
- **P1** is required for the Stage 1 user experience or operational acceptance.
- **P2** improves scale or usability and may follow the first accepted pilot.

## Epics and stories

| ID | Priority | Story | Acceptance summary | Depends on |
|---|---|---|---|---|
| S1-001 | P0 | Define crawl policy and URL safety model | Allowed hosts, robots snapshot, SSRF/redirect controls and budgets are testable | M0 |
| S1-002 | P0 | Define crawl-run state and terminal statuses | Invalid transitions fail; approval rejects transient items | S1-001 |
| S1-003 | P0 | Discover sitemap URLs | Sitemap indexes, canonical URLs and failures are recorded | S1-001 |
| S1-004 | P0 | Crawl static internal links | Frontier is bounded, resumable and cycle-safe | S1-001, S1-002 |
| S1-005 | P0 | Discover archive and pagination paths | Category/year/page traversal evidence is retained | S1-004 |
| S1-006 | P1 | Render selected dynamic pages | Escalation rule is observable and resource bounded | S1-004 |
| S1-007 | P0 | Download documents idempotently | Retries do not duplicate bytes or records | S1-002, S1-004 |
| S1-008 | P0 | Validate PDF integrity and metadata | Signature, size, parseability, pages and hash are recorded | S1-007 |
| S1-009 | P0 | Detect exact duplicates | SHA-256 groups duplicates without losing provenance | S1-008 |
| S1-010 | P1 | Flag near duplicates for review | Similarity evidence and threshold version are visible | S1-008 |
| S1-011 | P0 | Classify retries and permanent exceptions | Every failed URL has reason and attempt history | S1-007 |
| S1-012 | P0 | Reconcile discovery surfaces | Expected/observed/gap sets are queryable by surface | S1-003, S1-005, S1-011 |
| S1-013 | P0 | Enforce convergence stopping rule | Second pass yields no new qualifying canonical URL | S1-012 |
| S1-014 | P0 | Produce corpus manifest | Included/excluded documents and hashes validate deterministically | S1-008, S1-012 |
| S1-015 | P0 | Implement human approval gate | Reviewer can approve, reject or rerun; action is audited | S1-014 |
| S1-016 | P1 | Expose crawl control API | Create, start, pause, resume and cancel are contract-tested | S1-002 |
| S1-017 | P1 | Stream live run events | Reconnect preserves ordering and avoids silent event loss | S1-016 |
| S1-018 | P1 | Build New Crawl screen | Policy and budgets are previewed before execution | S1-001, S1-016 |
| S1-019 | P1 | Build Live Crawl screen | Counts and current/recent activity match backend state | S1-017 |
| S1-020 | P1 | Build Document Inventory screen | Provenance, validation, duplicate and exception filters work | S1-008, S1-010 |
| S1-021 | P1 | Build Coverage and Approval screen | Evidence, gaps, rerun and approval are usable | S1-012, S1-015 |
| S1-022 | P0 | Create deterministic fixture sites | Known truth sets cover static, dynamic, failure and security cases | S1-001 |
| S1-023 | P0 | Run AISATS pilot | Evidence report and limitation register reviewed | S1-001–S1-022 |
| S1-024 | P0 | Run Kolte Patil pilot | Generalisation gaps and adapter decisions recorded | S1-023 |
| S1-025 | P1 | Add operational observability | Structured logs, metrics and run correlation support diagnosis | S1-016 |
| S1-026 | P2 | Compare corpus versions | Added, removed and changed documents are visible | S1-014 |

## Recommended first sprint

1. S1-001 — crawl policy and URL safety
2. S1-002 — state model
3. S1-003 — sitemap discovery
4. S1-004 — static internal-link crawling
5. S1-007 — idempotent document retrieval
6. S1-022 — deterministic fixture sites in parallel with crawler work

## Backlog governance

- Create one GitHub issue per story when the M0 architecture is approved.
- Link issues to the owning milestone and pull request.
- Require acceptance evidence in each implementation PR.
- Add new site-specific logic through an adapter decision; do not hide it in generic crawler code.
- Split a story when it cannot be reviewed and tested independently.
