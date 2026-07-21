from io import BytesIO

import pymupdf

from okf_platform.convergence import compare_runs
from okf_platform.crawler import CrawlEngine
from okf_platform.models import CrawlReport, FetchResponse, UrlRecord, UrlStatus
from okf_platform.policy import CrawlPolicy
from okf_platform.robots import RobotsRules
from okf_platform.storage import load_report, save_report


def _response(url: str, status: int, content_type: str, body: bytes) -> FetchResponse:
    return FetchResponse(url, url, status, {"content-type": content_type}, body, 4)


def _pdf_bytes() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "reliability fixture")
    buffer = BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def test_robots_snapshot_enforces_rules_and_exposes_sitemaps() -> None:
    body = b"""User-agent: *
Disallow: /private
Crawl-delay: 2
Sitemap: https://example.com/sitemap.xml
"""
    rules = RobotsRules("https://example.com/robots.txt", 200, body, "OKF-AuditableCrawler/0.1")

    assert rules.allowed("https://example.com/public")
    assert not rules.allowed("https://example.com/private/report.pdf")
    assert rules.crawl_delay == 2
    assert rules.sitemap_urls == ("https://example.com/sitemap.xml",)
    assert len(rules.sha256) == 64


def test_retry_history_is_preserved_after_transient_failure() -> None:
    calls = 0

    def fetch(url: str) -> FetchResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _response(url, 503, "text/html", b"busy")
        return _response(url, 200, "text/html", b"done")

    delays: list[float] = []
    policy = CrawlPolicy(("example.com",), retry_backoff_seconds=0.5)
    report = CrawlEngine(policy, fetch, sleeper=delays.append).run("https://example.com")
    record = report.urls["https://example.com/"]

    assert record.status == UrlStatus.PAGE_PROCESSED
    assert [attempt.http_status for attempt in record.attempts] == [503, 200]
    assert delays == [0.5]


def test_recursive_sitemaps_discover_and_validate_pdf() -> None:
    pdf = _pdf_bytes()
    robots_body = b"Sitemap: https://example.com/sitemap-index.xml\nUser-agent: *\nAllow: /\n"
    robots = RobotsRules(
        "https://example.com/robots.txt", 200, robots_body, "OKF-AuditableCrawler/0.1"
    )
    responses = {
        "https://example.com/": _response("https://example.com/", 200, "text/html", b"home"),
        "https://example.com/sitemap-index.xml": _response(
            "https://example.com/sitemap-index.xml",
            200,
            "application/xml",
            b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/sitemap-docs.xml</loc></sitemap>
            </sitemapindex>""",
        ),
        "https://example.com/sitemap-docs.xml": _response(
            "https://example.com/sitemap-docs.xml",
            200,
            "application/xml",
            b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/report.pdf</loc></url>
            </urlset>""",
        ),
        "https://example.com/report.pdf": _response(
            "https://example.com/report.pdf", 200, "application/pdf", pdf
        ),
    }

    report = CrawlEngine(CrawlPolicy(("example.com",)), responses.__getitem__, robots=robots).run(
        "https://example.com"
    )

    assert report.ready_for_reconciliation
    assert report.urls["https://example.com/report.pdf"].status == UrlStatus.DOWNLOADED_VALID
    assert report.urls["https://example.com/sitemap-docs.xml"].discovery_method == "nested_sitemap"
    assert report.robots_sha256 == robots.sha256


def test_robots_disallowed_url_is_terminal_without_fetch() -> None:
    robots = RobotsRules(
        "https://example.com/robots.txt",
        200,
        b"User-agent: *\nDisallow: /private\n",
        "OKF-AuditableCrawler/0.1",
    )
    fetched: list[str] = []

    def fetch(url: str) -> FetchResponse:
        fetched.append(url)
        return _response(url, 200, "text/html", b'<a href="/private/report.pdf">private</a>')

    report = CrawlEngine(CrawlPolicy(("example.com",)), fetch, robots=robots).run(
        "https://example.com"
    )

    assert report.urls["https://example.com/private/report.pdf"].status == UrlStatus.EXCLUDED_BY_POLICY
    assert "https://example.com/private/report.pdf" not in fetched


def test_checkpoint_roundtrip_and_resume_unresolved_url(tmp_path) -> None:
    state_path = tmp_path / "run.json"
    previous = CrawlReport(target_url="https://example.com/")
    previous.urls["https://example.com/"] = UrlRecord(
        "https://example.com/", None, "target", 0, UrlStatus.PAGE_PROCESSED
    )
    previous.urls["https://example.com/retry"] = UrlRecord(
        "https://example.com/retry",
        "https://example.com/",
        "html_link",
        1,
        UrlStatus.UNRESOLVED_AFTER_RETRIES,
    )
    save_report(previous, state_path)

    loaded = load_report(state_path)
    report = CrawlEngine(
        CrawlPolicy(("example.com",)),
        lambda url: _response(url, 200, "text/html", b"recovered"),
        checkpoint=lambda value: save_report(value, state_path),
    ).run("https://example.com", previous_report=loaded)

    assert report.urls["https://example.com/retry"].status == UrlStatus.PAGE_PROCESSED
    assert load_report(state_path).ready_for_reconciliation


def test_convergence_requires_stable_urls_and_document_hashes() -> None:
    first = CrawlReport(target_url="https://example.com/")
    first.urls["https://example.com/"] = UrlRecord(
        "https://example.com/", None, "target", 0, UrlStatus.PAGE_PROCESSED
    )
    second = CrawlReport.from_dict(first.to_dict())

    assert compare_runs(first, second).converged
    second.urls["https://example.com/new"] = UrlRecord(
        "https://example.com/new", "https://example.com/", "html_link", 1, UrlStatus.PAGE_PROCESSED
    )
    evidence = compare_runs(first, second)
    assert not evidence.converged
    assert evidence.new_urls == ("https://example.com/new",)
