"""Command-line entry point for controlled discovery runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .convergence import compare_runs
from .crawler import CrawlEngine
from .policy import CrawlPolicy, canonicalise_url
from .robots import RobotsRules
from .storage import load_report, save_report
from .transport import HttpTransport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an auditable, PDF-focused website crawl")
    parser.add_argument("url", help="public website URL")
    parser.add_argument("--allow-host", action="append", default=[], help="additional exact host")
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--resume", action="store_true", help="resume queued/unresolved URLs from --output")
    parser.add_argument("--compare-to", type=Path, help="compare this run with an earlier report")
    parser.add_argument("--convergence-output", type=Path, default=Path("convergence-report.json"))
    parser.add_argument("--output", type=Path, default=Path("crawl-report.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = canonicalise_url(args.url)
    target_host = urlsplit(target).hostname or ""
    policy = CrawlPolicy(
        allowed_hosts=tuple([target_host, *args.allow_host]),
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        max_attempts=args.max_attempts,
    )
    transport = HttpTransport(policy)
    robots = RobotsRules.fetch(target, policy, transport.fetch)
    previous = load_report(args.output) if args.resume and args.output.exists() else None
    seed_urls = [] if robots.sitemap_urls else [canonicalise_url(urljoin(target, "/sitemap.xml"))]
    engine = CrawlEngine(
        policy,
        transport.fetch,
        robots=robots,
        checkpoint=lambda report: save_report(report, args.output),
    )
    report = engine.run(target, seed_urls=seed_urls, previous_report=previous)
    save_report(report, args.output)
    if args.compare_to:
        evidence = compare_runs(load_report(args.compare_to), report)
        args.convergence_output.write_text(
            json.dumps(evidence.to_dict(), indent=2), encoding="utf-8"
        )
    print(f"Wrote {len(report.urls)} URL records and {len(report.documents)} documents to {args.output}")
    return 0 if report.ready_for_reconciliation and not report.budget_exhausted else 2


if __name__ == "__main__":
    raise SystemExit(main())
