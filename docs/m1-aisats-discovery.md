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

## Not yet complete

- robots parser and crawl-delay enforcement;
- recursive sitemap fetching and reconciliation;
- retry/backoff attempt history;
- persistence/resume;
- dynamic Playwright discovery;
- archive/category coverage model;
- convergence comparison across two runs;
- UI and approval workflow.

Those items remain required before M1 can satisfy its milestone exit gate.
