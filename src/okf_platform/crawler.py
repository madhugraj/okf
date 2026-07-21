"""Bounded breadth-first document discovery engine."""

from __future__ import annotations

from collections import deque
import hashlib
from pathlib import PurePosixPath
import time
from typing import Callable
from urllib.parse import unquote, urlsplit

from .discovery import discover_html_links, discover_sitemap_urls
from .corpus import classify_asset
from .models import (
    AssetRecord,
    CrawlReport,
    DocumentRecord,
    FetchAttempt,
    FetchResponse,
    UrlRecord,
    UrlStatus,
)
from .pdf import validate_pdf
from .policy import CrawlPolicy, PolicyViolation, canonicalise_url, ensure_in_scope
from .robots import RobotsRules

Fetcher = Callable[[str], FetchResponse]
AssetSink = Callable[[FetchResponse, str | None, str], AssetRecord]


def looks_like_pdf(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf")


def _filename(url: str) -> str:
    name = PurePosixPath(unquote(urlsplit(url).path)).name
    return name or "document.pdf"


class CrawlEngine:
    """Deterministic mechanics; LangGraph may orchestrate this component."""

    def __init__(
        self,
        policy: CrawlPolicy,
        fetch: Fetcher,
        *,
        robots: RobotsRules | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        checkpoint: Callable[[CrawlReport], None] | None = None,
        asset_sink: AssetSink | None = None,
    ) -> None:
        self.policy = policy
        self.fetch = fetch
        self.robots = robots
        self.sleeper = sleeper
        self.checkpoint = checkpoint
        self.asset_sink = asset_sink

    def run(
        self,
        target_url: str,
        *,
        seed_urls: list[str] | None = None,
        previous_report: CrawlReport | None = None,
    ) -> CrawlReport:
        target = ensure_in_scope(target_url, self.policy)
        if previous_report and previous_report.target_url != target:
            raise ValueError("resume report target does not match requested target")
        report = previous_report or CrawlReport(target_url=target)
        report.budget_exhausted = False
        if self.robots:
            report.robots_url = self.robots.url
            report.robots_sha256 = self.robots.sha256
            report.robots_status = self.robots.status_code
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
            elif report.urls[url].status == UrlStatus.UNRESOLVED_AFTER_RETRIES:
                report.urls[url].status = UrlStatus.QUEUED
                report.urls[url].reason = None
                frontier.append(url)
            if referring_url:
                report.discovered_edges.append((referring_url, url))

        enqueue(target, None, "target", 0)
        for seed in seed_urls or []:
            enqueue(seed, target, "seed", 0)
        if self.robots:
            for sitemap_url in self.robots.sitemap_urls:
                enqueue(sitemap_url, self.robots.url, "robots_sitemap", 0)

        if previous_report:
            for url, record in report.urls.items():
                if record.status in {UrlStatus.QUEUED, UrlStatus.FETCHING, UrlStatus.UNRESOLVED_AFTER_RETRIES}:
                    record.status = UrlStatus.QUEUED
                    if url not in frontier:
                        frontier.append(url)

        seen_hashes = {
            document.sha256: document.duplicate_of or document.url
            for document in report.documents
            if document.valid_pdf
        }
        processed = 0
        while frontier:
            if processed >= self.policy.max_pages:
                report.budget_exhausted = True
                for queued_url in frontier:
                    report.urls[queued_url].status = UrlStatus.UNRESOLVED_AFTER_RETRIES
                    report.urls[queued_url].reason = "page budget exhausted"
                self._checkpoint(report)
                break

            url = frontier.popleft()
            record = report.urls[url]
            if record.depth > self.policy.max_depth:
                record.status = UrlStatus.EXCLUDED_BY_POLICY
                record.reason = "depth budget exceeded"
                self._checkpoint(report)
                continue

            if self.robots and not self.robots.allowed(url):
                record.status = UrlStatus.EXCLUDED_BY_POLICY
                record.reason = "disallowed by robots.txt snapshot"
                self._checkpoint(report)
                continue

            record.status = UrlStatus.FETCHING
            processed += 1
            response = self._fetch_with_retries(url, record)
            if response is None:
                self._checkpoint(report)
                continue

            record.http_status = response.status_code
            record.content_type = response.content_type
            if response.status_code == 404:
                record.status = UrlStatus.NOT_FOUND
                self._checkpoint(report)
                continue
            if response.status_code in {401, 403}:
                record.status = UrlStatus.ACCESS_DENIED
                self._checkpoint(report)
                continue
            if response.status_code >= 400:
                record.status = UrlStatus.PERMANENT_ERROR
                record.reason = f"HTTP {response.status_code}"
                self._checkpoint(report)
                continue

            if self.asset_sink:
                asset = self.asset_sink(response, record.referring_url, record.discovery_method)
            else:
                kind, extension, detected_mime = classify_asset(
                    response.final_url, response.content_type, response.body
                )
                asset = AssetRecord(
                    url=url,
                    final_url=response.final_url,
                    referring_url=record.referring_url,
                    kind=kind,
                    filename=PurePosixPath(unquote(urlsplit(response.final_url).path)).name
                    or f"index{extension}",
                    extension=extension,
                    declared_mime=response.content_type or None,
                    detected_mime=detected_mime,
                    byte_size=len(response.body),
                    sha256=hashlib.sha256(response.body).hexdigest(),
                    storage_uri=None,
                    discovered_by=record.discovery_method,
                )
            report.assets.append(asset)

            is_pdf = asset.kind.value == "pdf" or looks_like_pdf(response.final_url)
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
                self._checkpoint(report)
                continue

            is_sitemap = response.content_type in {"application/xml", "text/xml"} or "sitemap" in urlsplit(
                response.final_url
            ).path.lower()
            if is_sitemap:
                try:
                    discovered_urls, nested_sitemaps = discover_sitemap_urls(response.body)
                except Exception as exc:
                    record.status = UrlStatus.PERMANENT_ERROR
                    record.reason = f"invalid sitemap: {type(exc).__name__}: {exc}"
                    self._checkpoint(report)
                    continue
                for link in discovered_urls:
                    enqueue(link, url, "sitemap_url", record.depth + 1)
                for link in nested_sitemaps:
                    enqueue(link, url, "nested_sitemap", record.depth + 1)
                record.status = UrlStatus.PAGE_PROCESSED
                self._checkpoint(report)
                continue

            if response.content_type in {"text/html", "application/xhtml+xml", ""}:
                for link in discover_html_links(response.body, response.final_url):
                    enqueue(link, url, "html_link", record.depth + 1)
                record.status = UrlStatus.PAGE_PROCESSED
            else:
                record.status = UrlStatus.DOWNLOADED_VALID

            self._checkpoint(report)

        return report

    def _fetch_with_retries(self, url: str, record: UrlRecord) -> FetchResponse | None:
        for attempt_number in range(1, self.policy.max_attempts + 1):
            delay = self.robots.crawl_delay if self.robots else None
            if delay:
                self.sleeper(delay)
            try:
                response = self.fetch(url)
            except PolicyViolation as exc:
                record.attempts.append(FetchAttempt(attempt_number, f"policy: {exc}"))
                record.status = UrlStatus.EXCLUDED_BY_POLICY
                record.reason = str(exc)
                return None
            except Exception as exc:
                record.attempts.append(FetchAttempt(attempt_number, f"{type(exc).__name__}: {exc}"))
                if attempt_number == self.policy.max_attempts:
                    record.status = UrlStatus.UNRESOLVED_AFTER_RETRIES
                    record.reason = f"{type(exc).__name__}: {exc}"
                    return None
                self.sleeper(self.policy.retry_backoff_seconds * 2 ** (attempt_number - 1))
                continue

            record.attempts.append(
                FetchAttempt(attempt_number, "response", response.status_code, response.elapsed_ms)
            )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt_number == self.policy.max_attempts:
                    record.status = UrlStatus.UNRESOLVED_AFTER_RETRIES
                    record.http_status = response.status_code
                    record.reason = f"HTTP {response.status_code} after {attempt_number} attempts"
                    return None
                self.sleeper(self.policy.retry_backoff_seconds * 2 ** (attempt_number - 1))
                continue
            return response
        return None

    def _checkpoint(self, report: CrawlReport) -> None:
        if self.checkpoint:
            self.checkpoint(report)
