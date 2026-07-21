"""Bounded breadth-first document discovery engine."""

from __future__ import annotations

from collections import deque
from pathlib import PurePosixPath
from typing import Callable
from urllib.parse import unquote, urlsplit

from .discovery import discover_html_links
from .models import CrawlReport, DocumentRecord, FetchResponse, UrlRecord, UrlStatus
from .pdf import validate_pdf
from .policy import CrawlPolicy, PolicyViolation, canonicalise_url, ensure_in_scope

Fetcher = Callable[[str], FetchResponse]


def looks_like_pdf(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf")


def _filename(url: str) -> str:
    name = PurePosixPath(unquote(urlsplit(url).path)).name
    return name or "document.pdf"


class CrawlEngine:
    """Deterministic mechanics; LangGraph may orchestrate this component."""

    def __init__(self, policy: CrawlPolicy, fetch: Fetcher) -> None:
        self.policy = policy
        self.fetch = fetch

    def run(self, target_url: str, *, seed_urls: list[str] | None = None) -> CrawlReport:
        target = ensure_in_scope(target_url, self.policy)
        report = CrawlReport(target_url=target)
        frontier: deque[str] = deque()

        def enqueue(raw_url: str, referring_url: str | None, method: str, depth: int) -> None:
            try:
                url = ensure_in_scope(canonicalise_url(raw_url, base_url=referring_url), self.policy)
            except (PolicyViolation, ValueError) as exc:
                try:
                    excluded_url = canonicalise_url(raw_url, base_url=referring_url)
                except (PolicyViolation, ValueError):
                    return
                report.urls.setdefault(
                    excluded_url,
                    UrlRecord(excluded_url, referring_url, method, depth, UrlStatus.EXCLUDED_BY_POLICY, reason=str(exc)),
                )
                return
            if url not in report.urls:
                report.urls[url] = UrlRecord(url, referring_url, method, depth)
                frontier.append(url)
            if referring_url:
                report.discovered_edges.append((referring_url, url))

        enqueue(target, None, "target", 0)
        for seed in seed_urls or []:
            enqueue(seed, target, "seed", 0)

        seen_hashes: dict[str, str] = {}
        processed = 0
        while frontier:
            if processed >= self.policy.max_pages:
                report.budget_exhausted = True
                for queued_url in frontier:
                    report.urls[queued_url].status = UrlStatus.UNRESOLVED_AFTER_RETRIES
                    report.urls[queued_url].reason = "page budget exhausted"
                break

            url = frontier.popleft()
            record = report.urls[url]
            if record.depth > self.policy.max_depth:
                record.status = UrlStatus.EXCLUDED_BY_POLICY
                record.reason = "depth budget exceeded"
                continue

            record.status = UrlStatus.FETCHING
            processed += 1
            try:
                response = self.fetch(url)
            except PolicyViolation as exc:
                record.status = UrlStatus.EXCLUDED_BY_POLICY
                record.reason = str(exc)
                continue
            except Exception as exc:
                record.status = UrlStatus.UNRESOLVED_AFTER_RETRIES
                record.reason = f"{type(exc).__name__}: {exc}"
                continue

            record.http_status = response.status_code
            record.content_type = response.content_type
            if response.status_code == 404:
                record.status = UrlStatus.NOT_FOUND
                continue
            if response.status_code in {401, 403}:
                record.status = UrlStatus.ACCESS_DENIED
                continue
            if response.status_code >= 400:
                record.status = UrlStatus.PERMANENT_ERROR if response.status_code < 500 else UrlStatus.UNRESOLVED_AFTER_RETRIES
                record.reason = f"HTTP {response.status_code}"
                continue

            is_pdf = response.content_type == "application/pdf" or looks_like_pdf(response.final_url)
            if is_pdf:
                evidence = validate_pdf(response.body)
                duplicate_of = seen_hashes.get(evidence.sha256)
                if evidence.valid and duplicate_of:
                    record.status = UrlStatus.DUPLICATE_EXACT
                else:
                    record.status = UrlStatus.DOWNLOADED_VALID if evidence.valid else UrlStatus.DOWNLOADED_INVALID
                    if evidence.valid:
                        seen_hashes[evidence.sha256] = url
                report.documents.append(
                    DocumentRecord(
                        url=url,
                        referring_url=record.referring_url,
                        filename=_filename(response.final_url),
                        byte_size=evidence.byte_size,
                        sha256=evidence.sha256,
                        valid_pdf=evidence.valid,
                        page_count=evidence.page_count,
                        validation_error=evidence.error,
                        duplicate_of=duplicate_of,
                    )
                )
                continue

            if response.content_type in {"text/html", "application/xhtml+xml", ""}:
                for link in discover_html_links(response.body, response.final_url):
                    enqueue(link, url, "html_link", record.depth + 1)
                record.status = UrlStatus.PAGE_PROCESSED
            else:
                record.status = UrlStatus.EXCLUDED_BY_POLICY
                record.reason = f"unsupported content type: {response.content_type or 'unknown'}"

        return report
