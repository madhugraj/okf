"""Command-line entry point for controlled discovery runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from .crawler import CrawlEngine
from .policy import CrawlPolicy, canonicalise_url
from .transport import HttpTransport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an auditable, PDF-focused website crawl")
    parser.add_argument("url", help="public website URL")
    parser.add_argument("--allow-host", action="append", default=[], help="additional exact host")
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--max-depth", type=int, default=6)
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
    )
    transport = HttpTransport(policy)
    report = CrawlEngine(policy, transport.fetch).run(target)
    args.output.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(f"Wrote {len(report.urls)} URL records and {len(report.documents)} documents to {args.output}")
    return 0 if report.ready_for_reconciliation and not report.budget_exhausted else 2


if __name__ == "__main__":
    raise SystemExit(main())
