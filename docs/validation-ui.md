# Stage 1 Validation UI

## Purpose

The UI makes the crawl evidence reviewable by a non-developer. It does not declare a website complete automatically. It separates mechanical checks from the user's reconciliation decision and writes a hashed approval manifest only after both gates pass.

## Start locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
okf-ui
```

Open `http://127.0.0.1:8000`. The server binds to the local computer only; it is not exposed publicly.

## Validation workflow

1. Enter the public website URL and conservative crawl limits.
2. Watch URL, terminal-outcome, PDF and exception counts while the crawl runs.
3. Inspect the robots snapshot, budget state, every document and every exception.
4. Reconcile the visible site's navigation, archive pages, categories and known document lists against the inventory.
5. Download the JSON evidence bundle if an offline review is needed.
6. Start an independent verification crawl from the completed baseline.
7. Review any new URLs, missing URLs or new document hashes. Rerun or investigate until the two bounded runs converge.
8. Complete all four human confirmations and enter the reviewer name.
9. Approve the corpus. The system stores a manifest with the baseline run, verification run, reviewer, timestamp and SHA-256 of the approved report.

## Automatic approval blockers

Approval remains locked when:

- the selected run has not completed;
- it is not an independent second run;
- any discovered URL lacks a terminal status;
- the page budget was exhausted; or
- URL/document-hash convergence failed.

## Manual confirmations

Even after automated checks pass, the reviewer must explicitly confirm:

- document inventory and provenance were reviewed;
- failures, exclusions, invalid PDFs and duplicates were reviewed;
- robots and sitemap evidence were reviewed; and
- visible archive/category/navigation coverage was reconciled.

The approval manifest is evidence of a named review decision. It is not a mathematical claim that inaccessible, unlinked or undisclosed content does not exist.

## Local evidence

The default data directory is `.okf-data/`:

```text
.okf-data/
  runs/        # live and completed crawl evidence
  approvals/   # immutable approval manifests
```

Set `OKF_DATA_DIR` before starting the UI to use another location.
