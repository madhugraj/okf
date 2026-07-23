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
6. Start a repeat stability crawl from the completed baseline.
7. Review any new URLs, missing URLs or new document hashes. Rerun or investigate until the two bounded runs converge.
8. Start the separate read-only adversarial QA critic and resolve every blocker.
9. Inspect typed raw assets and their `corpus://` storage locations.
10. Complete all five human confirmations and enter the reviewer name.
11. Approve the corpus. The system stores a manifest with the baseline run, stability run, QA verdict, reviewer, timestamp and SHA-256 of the approved report.

## Reusing an approved website

The UI lists prior approvals under **Reuse an approved website**. Selecting one verifies the
immutable corpus-manifest hash and its approval metadata, then opens Stage 2, OKF and RAG without
starting Playwright, repeating scroll actions, rerunning discovery or rerunning adversarial QA.
Stage 2 continues to hash-check every referenced raw object before extracting it.

This is an approved-snapshot replay for downstream testing, not evidence that the live website is
unchanged. Use **Start a fresh controlled crawl** whenever the purpose is to detect new, removed or
changed website content. A damaged or mismatched approval/snapshot pair is shown as unavailable and
cannot be reused.

## Automatic approval blockers

Approval remains locked when:

- the selected run has not completed;
- it is not a separate repeat stability run;
- any discovered URL lacks a terminal status;
- the page budget was exhausted; or
- URL/document-hash convergence failed.
- adversarial QA has not completed; or
- the QA verdict is not `pass`.

## Manual confirmations

Even after automated checks pass, the reviewer must explicitly confirm:

- document inventory and provenance were reviewed;
- failures, exclusions, invalid PDFs and duplicates were reviewed;
- robots and sitemap evidence were reviewed; and
- visible archive/category/navigation coverage was reconciled.
- adversarial QA probes, findings, severities and verdict were reviewed.

The approval manifest is evidence of a named review decision. It is not a mathematical claim that inaccessible, unlinked or undisclosed content does not exist.

## Local evidence

The default data directory is `.okf-data/`:

```text
.okf-data/
  corpus/      # content-addressed typed raw bytes and SQLite provenance
  runs/        # live and completed crawl evidence
  approvals/   # immutable approval manifests
```

Set `OKF_DATA_DIR` before starting the UI to use another location.
