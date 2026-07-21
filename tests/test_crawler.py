from io import BytesIO

import pymupdf

from okf_platform.crawler import CrawlEngine
from okf_platform.models import FetchResponse, UrlStatus
from okf_platform.policy import CrawlPolicy


def _pdf_bytes() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "known fixture")
    buffer = BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def test_crawl_builds_terminal_inventory_and_exact_duplicate_evidence() -> None:
    pdf = _pdf_bytes()
    responses = {
        "https://example.com/": FetchResponse(
            "https://example.com/",
            "https://example.com/",
            200,
            {"content-type": "text/html"},
            b"""
            <a href="/archive">Archive</a>
            <a href="https://outside.example/report.pdf">External</a>
            """,
        ),
        "https://example.com/archive": FetchResponse(
            "https://example.com/archive",
            "https://example.com/archive",
            200,
            {"content-type": "text/html; charset=utf-8"},
            b"""
            <a href="/docs/report-a.pdf">A</a>
            <a href="/docs/report-b.pdf">B duplicate bytes</a>
            <a href="/docs/missing.pdf">missing</a>
            """,
        ),
        "https://example.com/docs/report-a.pdf": FetchResponse(
            "https://example.com/docs/report-a.pdf",
            "https://example.com/docs/report-a.pdf",
            200,
            {"content-type": "application/pdf"},
            pdf,
        ),
        "https://example.com/docs/report-b.pdf": FetchResponse(
            "https://example.com/docs/report-b.pdf",
            "https://example.com/docs/report-b.pdf",
            200,
            {"content-type": "application/pdf"},
            pdf,
        ),
        "https://example.com/docs/missing.pdf": FetchResponse(
            "https://example.com/docs/missing.pdf",
            "https://example.com/docs/missing.pdf",
            404,
            {"content-type": "text/html"},
            b"not found",
        ),
    }

    fetched: list[str] = []

    def fetch(url: str) -> FetchResponse:
        fetched.append(url)
        return responses[url]

    report = CrawlEngine(CrawlPolicy(("example.com",)), fetch).run("https://example.com")

    assert report.ready_for_reconciliation
    assert not report.budget_exhausted
    assert len(report.documents) == 2
    assert report.urls["https://example.com/docs/report-a.pdf"].status == UrlStatus.DOWNLOADED_VALID
    assert report.urls["https://example.com/docs/report-b.pdf"].status == UrlStatus.DUPLICATE_EXACT
    assert report.urls["https://example.com/docs/missing.pdf"].status == UrlStatus.NOT_FOUND
    assert report.urls["https://outside.example/report.pdf"].status == UrlStatus.EXCLUDED_BY_POLICY
    assert "https://outside.example/report.pdf" not in fetched
    assert report.documents[1].duplicate_of == "https://example.com/docs/report-a.pdf"


def test_page_budget_marks_remaining_urls_unresolved() -> None:
    homepage = FetchResponse(
        "https://example.com/",
        "https://example.com/",
        200,
        {"content-type": "text/html"},
        b'<a href="/one">one</a><a href="/two">two</a>',
    )
    report = CrawlEngine(CrawlPolicy(("example.com",), max_pages=1), lambda _: homepage).run(
        "https://example.com"
    )
    assert report.budget_exhausted
    assert report.ready_for_reconciliation
    assert report.urls["https://example.com/one"].status == UrlStatus.UNRESOLVED_AFTER_RETRIES
    assert report.urls["https://example.com/two"].status == UrlStatus.UNRESOLVED_AFTER_RETRIES
