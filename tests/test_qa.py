from okf_platform.models import AssetKind, AssetRecord, CrawlReport, UrlRecord, UrlStatus
from okf_platform.qa import CoverageCritic, ProbeResult, build_qa_graph


def _baseline() -> CrawlReport:
    report = CrawlReport("https://example.com/")
    report.urls[report.target_url] = UrlRecord(
        report.target_url, None, "target", 0, UrlStatus.PAGE_PROCESSED
    )
    report.assets.append(
        AssetRecord(
            report.target_url, report.target_url, None, AssetKind.HTML, "index.html", ".html",
            "text/html", "text/html", 10, "a" * 64, "corpus://objects/html/a", "crawler:http"
        )
    )
    return report


def test_qa_blocks_urls_found_only_by_independent_probe() -> None:
    report = CoverageCritic().evaluate(
        _baseline(),
        [ProbeResult("browser", frozenset({"https://example.com/", "https://example.com/hidden"}))],
    )
    assert report.verdict == "fail"
    assert report.findings[0].code == "QA_ONLY_URLS"


def test_qa_blocks_failed_tool_and_cannot_modify_baseline() -> None:
    baseline = _baseline()
    before = baseline.to_dict()
    report = CoverageCritic().evaluate(
        baseline, [ProbeResult("browser", status="failed", error="browser unavailable")]
    )
    assert report.verdict == "fail"
    assert report.findings[0].code == "QA_TOOL_FAILED"
    assert baseline.to_dict() == before


def test_qa_runs_in_a_separate_read_only_graph() -> None:
    class Probe:
        name = "independent-browser"

        def inspect(self, target_url, allowed_hosts):
            return ProbeResult(self.name, frozenset({target_url}))

    baseline = _baseline()
    result = build_qa_graph([Probe()]).invoke(
        {
            "baseline": baseline,
            "target_url": baseline.target_url,
            "allowed_hosts": ("example.com",),
        }
    )
    assert result["qa_report"].verdict == "pass"
