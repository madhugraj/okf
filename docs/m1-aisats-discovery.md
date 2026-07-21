# M1: AISATS Discovery Proof of Concept

## Scope of this pull request

M1 begins with a deterministic, fixture-tested crawl core. It does not yet claim an accepted AISATS corpus and it does not start OKF or RAG processing.

Implemented controls:

- exact allowed-host enforcement;
- URL canonicalisation and fragment removal;
- rejection of credential-bearing and non-public literal-IP URLs;
- DNS public-address checks immediately before public requests;
- manual validation of every redirect target;
- bounded crawl depth, page count, response size, timeout, and redirects;
- static HTML link discovery, including embedded PDFs;
- sitemap URL and sitemap-index parsing;
- PDF signature, end-marker, parseability, page count, byte size, and SHA-256 evidence;
- exact duplicate grouping without dropping provenance;
- terminal URL inventory and machine-readable JSON report;
- a two-node LangGraph wrapper: deterministic crawl, then readiness reconciliation.

## AISATS observations informing the pilot

The public navigation currently exposes a Credentials page at `/policies`. That page groups policy, CSR, and annual-return PDFs, while the Tenders page may legitimately contain no active documents at a given time. Documents are served from more than one same-host path, including `/storage/file/*.pdf` and `/pdf/*.pdf`; discovery must therefore follow links rather than assume one storage prefix.

These are observations, not hard-coded adapter rules.

## M1 execution sequence

1. Run all deterministic fixture, policy, PDF, and crawler tests.
2. Confirm the target site's robots and terms snapshot manually before a live run.
3. Run the CLI with conservative budgets against `https://www.aisats.in/`.
4. Reconcile homepage navigation, `/policies`, `/tenders`, any accessible sitemaps, all discovered PDF links, and failures.
5. Repeat discovery to measure convergence.
6. Publish the inventory and limitation register for human review.

The exact two-run procedure and reviewer gate are defined in the [AISATS pilot runbook](aisats-pilot-runbook.md).

## Increment 2 reliability controls

The second increment adds:

- a hashed robots.txt snapshot, allow/disallow enforcement, crawl-delay handling, and Sitemap directives;
- bounded retries with exponential backoff and URL-level attempt history;
- recursive sitemap-index traversal with the same domain and depth controls as HTML discovery;
- atomic JSON checkpoints and resume of queued, interrupted, or unresolved URLs;
- explicit comparison of successive runs for URL and document-hash convergence.

Convergence is evidence that repeated bounded discovery is stable. It is not, by itself, proof that invisible or inaccessible content does not exist.

## Still required before M1 exit

- dynamic Playwright discovery;
- archive/category coverage model;
- UI and approval workflow.

Those items remain required before M1 can satisfy its milestone exit gate.
