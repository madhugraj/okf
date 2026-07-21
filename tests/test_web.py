from __future__ import annotations

import time

from fastapi.testclient import TestClient

from okf_platform.models import CrawlReport, DocumentRecord, UrlRecord, UrlStatus
from okf_platform.run_service import RunConfig
from okf_platform.web import create_app


def _runner(config: RunConfig, checkpoint) -> CrawlReport:
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
    report.documents.append(
        DocumentRecord(document_url, config.target_url, "report.pdf", 1200, "b" * 64, True, 2)
    )
    checkpoint(report)
    return report


def _await_run(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        payload = client.get(f"/api/runs/{run_id}").json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("crawl did not finish")


def test_ui_serves_and_exposes_live_crawl_evidence(tmp_path) -> None:
    with TestClient(create_app(data_dir=tmp_path, runner=_runner)) as client:
        assert client.get("/").status_code == 200
        response = client.post("/api/runs", json={"url": "https://example.com/"})
        assert response.status_code == 202
        run = _await_run(client, response.json()["id"])

        assert run["status"] == "completed"
        assert run["summary"] == {
            "urls": 2,
            "terminal_urls": 2,
            "documents": 1,
            "exceptions": 0,
            "statuses": {"page_processed": 1, "downloaded_valid": 1},
        }
        assert not run["approval_gate"]["eligible"]
        assert client.get(f"/api/runs/{run['id']}/evidence").status_code == 200


def test_approval_requires_convergence_and_all_human_confirmations(tmp_path) -> None:
    with TestClient(create_app(data_dir=tmp_path, runner=_runner)) as client:
        first = client.post("/api/runs", json={"url": "https://example.com/"}).json()
        _await_run(client, first["id"])
        verification = client.post(f"/api/runs/{first['id']}/verification").json()
        second = _await_run(client, verification["id"])

        assert second["convergence"]["converged"]
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
            },
        )
        assert approval.status_code == 200
        assert approval.json()["id"].startswith("corpus-")
        assert len(approval.json()["report_sha256"]) == 64
        assert client.post(
            f"/api/runs/{second['id']}/approval",
            json={
                "reviewer": "Madhu",
                "inventory_reviewed": True,
                "exceptions_reviewed": True,
                "robots_reviewed": True,
                "archive_coverage_reviewed": True,
            },
        ).status_code == 409
