from __future__ import annotations

import time

from fastapi.testclient import TestClient
import fitz

from okf_platform.corpus import LocalCorpusStore
from okf_platform.models import (
    CrawlReport,
    DocumentRecord,
    FetchResponse,
    UrlRecord,
    UrlStatus,
)
from okf_platform.qa import FindingSeverity, ProbeResult, QaFinding, QaReport
from okf_platform.run_service import RunConfig
from okf_platform.web import create_app


def _pdf_fixture() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "AISATS annual report")
    payload = document.tobytes()
    document.close()
    return payload


PDF_FIXTURE = _pdf_fixture()


def _runner(config: RunConfig, checkpoint, run_id, data_dir) -> CrawlReport:
    report = CrawlReport(
        target_url=config.target_url,
        robots_url=f"{config.target_url.rstrip('/')}/robots.txt",
        robots_sha256="a" * 64,
        robots_status=200,
    )
    report.urls[config.target_url] = UrlRecord(
        config.target_url, None, "target", 0, UrlStatus.PAGE_PROCESSED, 200
    )
    checkpoint(report)
    document_url = f"{config.target_url.rstrip('/')}/report.pdf"
    report.urls[document_url] = UrlRecord(
        document_url,
        config.target_url,
        "html_link",
        1,
        UrlStatus.DOWNLOADED_VALID,
        200,
        content_type="application/pdf",
    )
    corpus = LocalCorpusStore(data_dir / "corpus")
    html = corpus.save(
        run_id,
        FetchResponse(
            config.target_url,
            config.target_url,
            200,
            {"content-type": "text/html"},
            b"<h1>AISATS</h1><p>Ground handling services.</p>",
        ),
        referring_url=None,
        discovered_by="crawler:target",
    )
    pdf_bytes = PDF_FIXTURE
    pdf = corpus.save(
        run_id,
        FetchResponse(
            document_url,
            document_url,
            200,
            {"content-type": "application/pdf"},
            pdf_bytes,
        ),
        referring_url=config.target_url,
        discovered_by="crawler:html_link",
    )
    report.documents.append(
        DocumentRecord(
            document_url,
            config.target_url,
            "report.pdf",
            len(pdf_bytes),
            pdf.sha256,
            True,
            1,
        )
    )
    report.assets.extend([html, pdf])
    checkpoint(report)
    return report


def _qa_runner(config: RunConfig, report: CrawlReport) -> QaReport:
    return QaReport(
        "pass",
        [ProbeResult("playwright_rendered_dom_and_network", frozenset(report.urls))],
        [QaFinding("QA_CLEAR", FindingSeverity.INFO, "No gaps")],
    )


def _await_run(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        payload = client.get(f"/api/runs/{run_id}").json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("crawl did not finish")


def test_ui_serves_and_exposes_live_crawl_evidence(tmp_path) -> None:
    with TestClient(create_app(data_dir=tmp_path, runner=_runner, qa_runner=_qa_runner)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Reuse an approved website" in page.text
        assert 'id="approved-corpus-select"' in page.text
        rag_config = client.get("/api/rag/config")
        assert rag_config.status_code == 200
        assert rag_config.json()["retrieval"]["sparse"] == "BM25"
        response = client.post("/api/runs", json={"url": "https://example.com/"})
        assert response.status_code == 202
        run = _await_run(client, response.json()["id"])

        assert run["status"] == "completed"
        assert run["summary"] == {
            "urls": 2,
            "terminal_urls": 2,
            "documents": 1,
            "assets": 2,
            "asset_types": {"html": 1, "pdf": 1},
            "exceptions": 0,
            "statuses": {"page_processed": 1, "downloaded_valid": 1},
        }
        assert not run["approval_gate"]["eligible"]
        assert client.get(f"/api/runs/{run['id']}/evidence").status_code == 200


def test_approval_requires_convergence_and_all_human_confirmations(tmp_path) -> None:
    with TestClient(create_app(data_dir=tmp_path, runner=_runner, qa_runner=_qa_runner)) as client:
        first = client.post("/api/runs", json={"url": "https://example.com/"}).json()
        _await_run(client, first["id"])
        verification = client.post(f"/api/runs/{first['id']}/verification").json()
        second = _await_run(client, verification["id"])

        assert second["convergence"]["converged"]
        assert not second["approval_gate"]["eligible"]
        qa_started = client.post(f"/api/runs/{second['id']}/qa")
        assert qa_started.status_code == 202
        second = _await_qa(client, second["id"])
        assert second["qa"]["report"]["verdict"] == "pass"
        assert second["approval_gate"]["eligible"]
        incomplete = client.post(
            f"/api/runs/{second['id']}/approval",
            json={"reviewer": "Madhu", "inventory_reviewed": True},
        )
        assert incomplete.status_code == 409

        approval = client.post(
            f"/api/runs/{second['id']}/approval",
            json={
                "reviewer": "Madhu",
                "inventory_reviewed": True,
                "exceptions_reviewed": True,
                "robots_reviewed": True,
                "archive_coverage_reviewed": True,
                "qa_findings_reviewed": True,
            },
        )
        assert approval.status_code == 200
        assert approval.json()["id"].startswith("corpus-")
        assert len(approval.json()["report_sha256"]) == 64
        assert approval.json()["corpus_snapshot"]["object_count"] == 2
        approved_corpora = client.get("/api/corpora")
        assert approved_corpora.status_code == 200
        assert approved_corpora.json() == [
            {
                "id": approval.json()["id"],
                "target_url": "https://example.com/",
                "approved_at": approval.json()["approved_at"],
                "reviewer": "Madhu",
                "qa_effective_verdict": "pass",
                "accepted_qa_exception_count": 0,
                "source_run_id": second["id"],
                "baseline_run_id": first["id"],
                "corpus_snapshot": approval.json()["corpus_snapshot"],
                "integrity": "verified",
                "reusable": True,
            }
        ]
        extraction = client.post(
            f"/api/corpora/{approval.json()['id']}/stage2/extraction"
        )
        assert extraction.status_code == 200
        assert extraction.json()["text_unit_count"] == 2
        assert client.post(
            f"/api/runs/{second['id']}/approval",
            json={
                "reviewer": "Madhu",
                "inventory_reviewed": True,
                "exceptions_reviewed": True,
                "robots_reviewed": True,
                "archive_coverage_reviewed": True,
                "qa_findings_reviewed": True,
            },
        ).status_code == 409


def test_damaged_approved_snapshot_is_visible_but_cannot_be_reused(tmp_path) -> None:
    with TestClient(create_app(data_dir=tmp_path, runner=_runner, qa_runner=_qa_runner)) as client:
        first = client.post("/api/runs", json={"url": "https://example.com/"}).json()
        _await_run(client, first["id"])
        second = client.post(f"/api/runs/{first['id']}/verification").json()
        _await_run(client, second["id"])
        client.post(f"/api/runs/{second['id']}/qa")
        _await_qa(client, second["id"])
        approval = client.post(
            f"/api/runs/{second['id']}/approval",
            json={
                "reviewer": "Madhu",
                "inventory_reviewed": True,
                "exceptions_reviewed": True,
                "robots_reviewed": True,
                "archive_coverage_reviewed": True,
                "qa_findings_reviewed": True,
            },
        ).json()

        manifest = tmp_path / "corpora" / approval["id"] / "manifest.json"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                "example.com", "tampered.example"
            ),
            encoding="utf-8",
        )
        listed = client.get("/api/corpora").json()

        assert listed[0]["id"] == approval["id"]
        assert listed[0]["integrity"] == "failed"
        assert listed[0]["reusable"] is False
        assert "integrity verification" in listed[0]["integrity_error"]


def _await_qa(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        payload = client.get(f"/api/runs/{run_id}").json()
        if payload["qa"]["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("QA did not finish")


def _qa_gap_runner(config: RunConfig, report: CrawlReport) -> QaReport:
    return QaReport(
        "fail",
        [ProbeResult("independent-browser", frozenset(report.urls))],
        [
            QaFinding(
                "UNRESOLVED_BASELINE",
                FindingSeverity.BLOCKER,
                "Crawler has 1 invalid or unresolved outcome",
                ("https://example.com/missing image.png",),
            )
        ],
    )


def _qa_discovery_and_url_gap_runner(config: RunConfig, report: CrawlReport) -> QaReport:
    return QaReport(
        "fail",
        [ProbeResult("independent-browser", frozenset(report.urls))],
        [
            QaFinding(
                "DISCOVERY_TOOL_FAILED",
                FindingSeverity.BLOCKER,
                "Crawler evidence is incomplete because a rendered discovery tool failed",
            ),
            QaFinding(
                "UNRESOLVED_BASELINE",
                FindingSeverity.BLOCKER,
                "Crawler has 1 invalid or unresolved outcome",
                ("https://example.com/decorative image.png",),
            ),
        ],
    )


def test_ui_api_builds_and_compares_okf_and_rag(tmp_path) -> None:
    with TestClient(create_app(data_dir=tmp_path, runner=_runner, qa_runner=_qa_runner)) as client:
        first = client.post("/api/runs", json={"url": "https://example.com/"}).json()
        _await_run(client, first["id"])
        second = client.post(f"/api/runs/{first['id']}/verification").json()
        _await_run(client, second["id"])
        client.post(f"/api/runs/{second['id']}/qa")
        _await_qa(client, second["id"])
        approval = client.post(
            f"/api/runs/{second['id']}/approval",
            json={
                "reviewer": "Madhu",
                "inventory_reviewed": True,
                "exceptions_reviewed": True,
                "robots_reviewed": True,
                "archive_coverage_reviewed": True,
                "qa_findings_reviewed": True,
            },
        ).json()
        corpus_id = approval["id"]

        assert client.post(f"/api/corpora/{corpus_id}/stage2/extraction").status_code == 200
        okf = client.post(f"/api/corpora/{corpus_id}/okf/build")
        rag = client.post(f"/api/corpora/{corpus_id}/rag/build")
        assert okf.status_code == 200
        assert rag.status_code == 200
        comparison = client.post(
            f"/api/corpora/{corpus_id}/compare",
            json={"question": "What services are available?"},
        )
        assert comparison.status_code == 200
        assert comparison.json()["same_corpus"] is True
        evaluation = client.post(
            f"/api/corpora/{corpus_id}/evaluate",
            json={"cases": [{"question": "What services are available?"}]},
        )
        assert evaluation.status_code == 200
        assert evaluation.json()["summary"]["okf"]["case_count"] == 1


def test_reviewer_can_accept_a_coverage_gap_with_audited_exception(tmp_path) -> None:
    with TestClient(create_app(data_dir=tmp_path, runner=_runner, qa_runner=_qa_gap_runner)) as client:
        first = client.post("/api/runs", json={"url": "https://example.com/"}).json()
        _await_run(client, first["id"])
        second = client.post(f"/api/runs/{first['id']}/verification").json()
        _await_run(client, second["id"])
        client.post(f"/api/runs/{second['id']}/qa")
        run = _await_qa(client, second["id"])
        assert run["approval_gate"]["eligible_with_exceptions"]
        finding = run["qa"]["report"]["findings"][0]
        payload = {
            "reviewer": "Madhu",
            "inventory_reviewed": True,
            "exceptions_reviewed": True,
            "robots_reviewed": True,
            "archive_coverage_reviewed": True,
            "qa_findings_reviewed": True,
            "qa_exceptions": [
                {
                    "finding_fingerprint": finding["fingerprint"],
                    "accepted": True,
                    "reason": "The missing decorative image does not affect the knowledge scope.",
                    "residual_risk": "Visual branding may be incomplete.",
                }
            ],
        }
        approval = client.post(f"/api/runs/{second['id']}/approval", json=payload)
        assert approval.status_code == 200
        assert approval.json()["qa_effective_verdict"] == "accepted_with_exceptions"
        assert approval.json()["accepted_qa_exceptions"][0]["accepted_by"] == "Madhu"


def test_reviewer_can_accept_discovery_failure_and_unresolved_assets_together(
    tmp_path,
) -> None:
    with TestClient(
        create_app(
            data_dir=tmp_path,
            runner=_runner,
            qa_runner=_qa_discovery_and_url_gap_runner,
        )
    ) as client:
        first = client.post("/api/runs", json={"url": "https://example.com/"}).json()
        _await_run(client, first["id"])
        second = client.post(f"/api/runs/{first['id']}/verification").json()
        _await_run(client, second["id"])
        client.post(f"/api/runs/{second['id']}/qa")
        run = _await_qa(client, second["id"])

        assert run["approval_gate"]["eligible_with_exceptions"]
        findings = run["qa"]["report"]["findings"]
        assert {finding["code"] for finding in findings} == {
            "DISCOVERY_TOOL_FAILED",
            "UNRESOLVED_BASELINE",
        }
        assert all(finding["waivable"] for finding in findings)

        payload = {
            "reviewer": "Madhu",
            "inventory_reviewed": True,
            "exceptions_reviewed": True,
            "robots_reviewed": True,
            "archive_coverage_reviewed": True,
            "qa_findings_reviewed": True,
            "qa_exceptions": [
                {
                    "finding_fingerprint": finding["fingerprint"],
                    "accepted": True,
                    "reason": (
                        "The remaining evidence is adequate for this bounded knowledge corpus."
                    ),
                    "residual_risk": (
                        "Rendered-only links or decorative assets may remain undiscovered."
                    ),
                }
                for finding in findings
            ],
        }
        approval = client.post(f"/api/runs/{second['id']}/approval", json=payload)

        assert approval.status_code == 200
        assert approval.json()["qa_effective_verdict"] == "accepted_with_exceptions"
        assert len(approval.json()["accepted_qa_exceptions"]) == 2
