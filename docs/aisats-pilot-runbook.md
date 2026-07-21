# Controlled AISATS Pilot Runbook

## Purpose

This runbook produces two independently persisted AISATS discovery reports and a convergence comparison. It does not permit an automatic completeness claim; a reviewer must still reconcile navigation, archive/category coverage, failures, robots evidence, and document inventory.

## Preconditions

- Run from a network that permits public HTTPS access to `www.aisats.in`.
- Install the project in an isolated Python 3.12 environment.
- Do not add other domains or subdomains unless their inclusion is reviewed.
- Stop if the robots snapshot cannot be retrieved or reviewed.

## Run 1

```bash
okf-crawl https://www.aisats.in/ \
  --max-pages 500 \
  --max-depth 8 \
  --max-attempts 3 \
  --output evidence/aisats-run-1.json
```

The crawler stores the robots URL, HTTP status and SHA-256 in the report. It obeys disallow rules and any declared crawl delay, follows recursively declared sitemaps, and checkpoints after each terminal URL.

If interrupted, resume only from the same output file:

```bash
okf-crawl https://www.aisats.in/ \
  --max-pages 500 \
  --max-depth 8 \
  --max-attempts 3 \
  --resume \
  --output evidence/aisats-run-1.json
```

## Run 2 and convergence

Run the second discovery independently rather than resuming Run 1:

```bash
okf-crawl https://www.aisats.in/ \
  --max-pages 500 \
  --max-depth 8 \
  --max-attempts 3 \
  --output evidence/aisats-run-2.json \
  --compare-to evidence/aisats-run-1.json \
  --convergence-output evidence/aisats-convergence.json
```

## Mandatory reviewer checks

1. Confirm the robots snapshot and whether a sitemap was declared or `/sitemap.xml` was probed.
2. Reconcile the visible navigation, including Announcements, Tenders and Credentials.
3. Review every `excluded_by_policy`, `access_denied`, `permanent_error` and `unresolved_after_retries` record.
4. Confirm every PDF has a source page, integrity evidence and a terminal status.
5. Review exact duplicate groups without discarding their distinct source URLs.
6. Confirm the convergence report contains no new or missing URLs and no new document hashes.
7. Record dynamic or JavaScript-only surfaces that the static crawler could not inspect.

Only after these checks may the inventory move to the Stage 1 human approval screen. Convergence is necessary evidence, not sufficient proof of completeness.

## Current execution limitation

The development runtime used for Increment 2 does not allow outbound requests to `aisats.in`, so no live report is committed with this increment. Fixture-based tests validate the mechanics; the first controlled evidence bundle remains an explicit follow-up activity.
