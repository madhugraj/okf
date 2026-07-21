"""Persistent crawl-run service used by the validation UI."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Callable
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from .convergence import compare_runs
from .corpus import LocalCorpusStore
from .crawler import CrawlEngine
from .deep_scrape import BrowserDeepScraper
from .governance import assess_qa_exceptions, decorate_findings
from .models import CrawlReport, FetchResponse, TERMINAL_STATUSES, UrlStatus
from .policy import CrawlPolicy, canonicalise_url
from .robots import RobotsRules
from .transport import HttpTransport
from .qa import QaReport, build_qa_graph
from .snapshot import freeze_corpus_snapshot
from .workflow import build_discovery_graph


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True, slots=True)
class RunConfig:
    target_url: str
    allowed_hosts: tuple[str, ...]
    max_pages: int = 500
    max_depth: int = 8
    max_attempts: int = 3

    @classmethod
    def create(
        cls,
        target_url: str,
        *,
        allowed_hosts: tuple[str, ...] = (),
        max_pages: int = 500,
        max_depth: int = 8,
        max_attempts: int = 3,
    ) -> RunConfig:
        target = canonicalise_url(target_url)
        host = urlsplit(target).hostname or ""
        policy = CrawlPolicy(
            allowed_hosts=(host, *allowed_hosts),
            max_pages=max_pages,
            max_depth=max_depth,
            max_attempts=max_attempts,
        )
        return cls(target, policy.allowed_hosts, max_pages, max_depth, max_attempts)


Runner = Callable[[RunConfig, Callable[[CrawlReport], None], str, Path], CrawlReport]
QaRunner = Callable[[RunConfig, CrawlReport], QaReport]


def execute_crawl(
    config: RunConfig,
    checkpoint: Callable[[CrawlReport], None],
    run_id: str,
    data_dir: Path,
) -> CrawlReport:
    policy = CrawlPolicy(
        allowed_hosts=config.allowed_hosts,
        max_pages=config.max_pages,
        max_depth=config.max_depth,
        max_attempts=config.max_attempts,
    )
    transport = HttpTransport(policy)
    robots = RobotsRules.fetch(config.target_url, policy, transport.fetch)
    browser = BrowserDeepScraper(max_pages=min(config.max_pages, 100), url_filter=robots.allowed)
    browser_result = browser.inspect(config.target_url, config.allowed_hosts)
    seeds = list(browser_result.urls)
    if not robots.sitemap_urls:
        seeds.append(canonicalise_url(urljoin(config.target_url, "/sitemap.xml")))
    corpus = LocalCorpusStore(data_dir / "corpus")
    engine = CrawlEngine(
        policy,
        transport.fetch,
        robots=robots,
        checkpoint=checkpoint,
        asset_sink=lambda response, referrer, method: corpus.save(
            run_id,
            response,
            referring_url=referrer,
            discovered_by=f"crawler:{method}",
        ),
    )
    discovery_state = build_discovery_graph(engine).invoke(
        {"target_url": config.target_url, "seed_urls": seeds}
    )
    report = discovery_state["report"]
    for url, html in browser.rendered_html.items():
        report.assets.append(
            corpus.save(
                run_id,
                FetchResponse(url, url, 200, {"content-type": "text/html"}, html),
                referring_url=config.target_url if url != config.target_url else None,
                discovered_by="crawler:playwright_rendered_dom",
            )
        )
    report.discovery_evidence = [
        {
            "agent": "discovery_crawler",
            "tool": "http_sitemap_recursive_crawler",
            "status": "passed",
            "discovered_urls": len(report.urls),
        },
        {
            "agent": "discovery_crawler",
            "tool": browser_result.tool,
            "status": browser_result.status,
            "discovered_urls": len(browser_result.urls),
            "error": browser_result.error,
            "evidence": browser_result.evidence,
        },
    ]
    checkpoint(report)
    return report


def execute_qa(config: RunConfig, report: CrawlReport) -> QaReport:
    """Run an independent, read-only browser-first challenge of crawler evidence."""

    policy = CrawlPolicy(
        allowed_hosts=config.allowed_hosts,
        max_pages=config.max_pages,
        max_depth=config.max_depth,
        max_attempts=config.max_attempts,
    )
    transport = HttpTransport(policy)
    robots = RobotsRules.fetch(config.target_url, policy, transport.fetch)
    graph = build_qa_graph(
        [
            BrowserDeepScraper(
                max_pages=min(config.max_pages, 150),
                scroll_rounds=5,
                url_filter=robots.allowed,
            )
        ],
    )
    return graph.invoke(
        {
            "baseline": report,
            "target_url": config.target_url,
            "allowed_hosts": config.allowed_hosts,
        }
    )["qa_report"]


class RunService:
    """Create runs, expose live evidence, and enforce the human approval gate."""

    checklist_fields = (
        "inventory_reviewed",
        "exceptions_reviewed",
        "robots_reviewed",
        "archive_coverage_reviewed",
        "qa_findings_reviewed",
    )

    def __init__(
        self,
        data_dir: Path,
        *,
        runner: Runner = execute_crawl,
        qa_runner: QaRunner = execute_qa,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.runs_dir = data_dir / "runs"
        self.approvals_dir = data_dir / "approvals"
        self.runner = runner
        self.qa_runner = qa_runner
        self.executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="okf-crawl")
        self._lock = RLock()

    def start_run(self, config: RunConfig, *, baseline_run_id: str | None = None) -> dict[str, object]:
        run_id = uuid4().hex
        payload: dict[str, object] = {
            "id": run_id,
            "status": "queued",
            "created_at": _now(),
            "started_at": None,
            "completed_at": None,
            "baseline_run_id": baseline_run_id,
            "config": {**asdict(config), "allowed_hosts": list(config.allowed_hosts)},
            "report": None,
            "convergence": None,
            "qa": {"status": "not_started", "report": None, "error": None},
            "error": None,
            "approval": None,
        }
        self._write_run(payload)
        self.executor.submit(self._execute, run_id, config, baseline_run_id)
        return self.get_run(run_id)

    def start_verification(self, baseline_run_id: str) -> dict[str, object]:
        baseline = self._read_run(baseline_run_id)
        if baseline["status"] != "completed":
            raise ValueError("the baseline crawl must complete before verification")
        config_data = dict(baseline["config"])
        config_data["allowed_hosts"] = tuple(config_data["allowed_hosts"])
        return self.start_run(RunConfig(**config_data), baseline_run_id=baseline_run_id)

    def get_run(self, run_id: str) -> dict[str, object]:
        payload = self._read_run(run_id)
        return self._decorate(payload)

    def start_qa(self, run_id: str) -> dict[str, object]:
        with self._lock:
            run = self._read_run(run_id)
            if run["status"] != "completed" or not run.get("baseline_run_id"):
                raise ValueError("complete the stability crawl before adversarial QA")
            if not (run.get("convergence") or {}).get("converged"):
                raise ValueError("the stability crawl must converge before adversarial QA")
            if (run.get("qa") or {}).get("status") in {"queued", "running", "completed"}:
                raise ValueError("QA has already been started for this run")
            run["qa"] = {"status": "queued", "report": None, "error": None}
            self._write_run(run)
        self.executor.submit(self._execute_qa, run_id)
        return self.get_run(run_id)

    def list_runs(self) -> list[dict[str, object]]:
        runs = [self._decorate(json.loads(path.read_text(encoding="utf-8"))) for path in self.runs_dir.glob("*.json")]
        return sorted(runs, key=lambda item: str(item["created_at"]), reverse=True)

    def approve(
        self,
        run_id: str,
        reviewer: str,
        checklist: dict[str, bool],
        qa_exceptions: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        if not reviewer.strip():
            raise ValueError("reviewer name is required")
        if not all(checklist.get(field) is True for field in self.checklist_fields):
            raise ValueError("every review confirmation is required")

        with self._lock:
            run = self._read_run(run_id)
            if run.get("approval"):
                raise ValueError("this verification run already has an approved corpus manifest")
            exception_assessment = assess_qa_exceptions(
                (run.get("qa") or {}).get("report"),
                qa_exceptions or [],
                reviewer=reviewer.strip(),
            )
            eligibility = self._eligibility(run, qa_exceptions or [])
            if not eligibility["eligible"]:
                raise ValueError("approval gate is locked: " + "; ".join(eligibility["blockers"]))
            report = dict(run["report"])
            report_hash = hashlib.sha256(
                json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            approval_id = f"corpus-{uuid4().hex[:12]}"
            approval: dict[str, object] = {
                "id": approval_id,
                "approved_at": _now(),
                "reviewer": reviewer.strip(),
                "run_id": run_id,
                "baseline_run_id": run["baseline_run_id"],
                "target_url": run["config"]["target_url"],
                "report_sha256": report_hash,
                "qa_verdict": run["qa"]["report"]["verdict"],
                "qa_effective_verdict": (
                    "accepted_with_exceptions"
                    if exception_assessment["accepted"]
                    else run["qa"]["report"]["verdict"]
                ),
                "qa_report": run["qa"]["report"],
                "accepted_qa_exceptions": exception_assessment["accepted"],
                "checklist": {field: True for field in self.checklist_fields},
            }
            snapshot = freeze_corpus_snapshot(self.data_dir, approval, report)
            approval["corpus_snapshot"] = snapshot
            _atomic_json(self.approvals_dir / f"{approval_id}.json", approval)
            run["approval"] = approval
            self._write_run(run)
            return approval

    def evidence(self, run_id: str) -> dict[str, object]:
        return self._read_run(run_id)

    def _execute(self, run_id: str, config: RunConfig, baseline_run_id: str | None) -> None:
        with self._lock:
            run = self._read_run(run_id)
            run["status"] = "running"
            run["started_at"] = _now()
            self._write_run(run)
        try:
            report = self.runner(
                config,
                lambda value: self._checkpoint(run_id, value),
                run_id,
                self.data_dir,
            )
            with self._lock:
                run = self._read_run(run_id)
                run["report"] = report.to_dict()
                if baseline_run_id:
                    baseline = self._read_run(baseline_run_id)
                    run["convergence"] = compare_runs(
                        CrawlReport.from_dict(baseline["report"]), report
                    ).to_dict()
                run["status"] = "completed"
                run["completed_at"] = _now()
                self._write_run(run)
        except Exception as exc:
            with self._lock:
                run = self._read_run(run_id)
                run["status"] = "failed"
                run["completed_at"] = _now()
                run["error"] = f"{type(exc).__name__}: {exc}"
                self._write_run(run)

    def _execute_qa(self, run_id: str) -> None:
        with self._lock:
            run = self._read_run(run_id)
            run["qa"]["status"] = "running"
            self._write_run(run)
        try:
            config_data = dict(run["config"])
            config_data["allowed_hosts"] = tuple(config_data["allowed_hosts"])
            report = self.qa_runner(RunConfig(**config_data), CrawlReport.from_dict(run["report"]))
            with self._lock:
                run = self._read_run(run_id)
                run["qa"] = {"status": "completed", "report": report.to_dict(), "error": None}
                self._write_run(run)
        except Exception as exc:
            with self._lock:
                run = self._read_run(run_id)
                run["qa"] = {
                    "status": "failed",
                    "report": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                self._write_run(run)

    def _checkpoint(self, run_id: str, report: CrawlReport) -> None:
        with self._lock:
            run = self._read_run(run_id)
            run["report"] = report.to_dict()
            self._write_run(run)

    def _eligibility(
        self,
        run: dict[str, object],
        qa_exceptions: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        blockers: list[str] = []
        hard_blockers: list[str] = []
        report = run.get("report") or {}
        if run.get("status") != "completed":
            blockers.append("verification run is not complete")
        if not run.get("baseline_run_id"):
            blockers.append("a separate repeat stability run is required")
        if not report.get("ready_for_reconciliation"):
            blockers.append("some discovered URLs are not terminal")
        if report.get("budget_exhausted"):
            blockers.append("crawl budget was exhausted")
        convergence = run.get("convergence") or {}
        if not convergence.get("converged"):
            blockers.append("the two runs have not converged")
        qa = run.get("qa") or {}
        waiver_assessment: dict[str, object] = {"accepted": [], "pending": [], "hard": []}
        if qa.get("status") != "completed":
            message = "adversarial QA is not complete"
            blockers.append(message)
            hard_blockers.append(message)
        else:
            waiver_assessment = assess_qa_exceptions(
                qa.get("report"), qa_exceptions or []
            )
            if waiver_assessment["hard"]:
                message = "adversarial QA found non-bypassable integrity or tool failures"
                blockers.append(message)
                hard_blockers.append(message)
            if waiver_assessment["pending"]:
                blockers.append("adversarial QA found coverage gaps requiring explicit risk acceptance")
        non_qa = [item for item in blockers if not item.startswith("adversarial QA")]
        hard_blockers.extend(non_qa)
        return {
            "eligible": not blockers,
            "eligible_with_exceptions": not hard_blockers and bool(waiver_assessment["pending"]),
            "blockers": blockers,
            "hard_blockers": list(dict.fromkeys(hard_blockers)),
            "waiveable_findings": waiver_assessment["pending"],
            "accepted_exceptions": waiver_assessment["accepted"],
        }

    def _decorate(self, run: dict[str, object]) -> dict[str, object]:
        payload = json.loads(json.dumps(run))
        qa = payload.get("qa") or {}
        if qa.get("report"):
            qa["report"]["findings"] = decorate_findings(qa["report"])
        report = payload.get("report") or {}
        urls = report.get("urls", {})
        statuses: dict[str, int] = {}
        terminal = 0
        for record in urls.values():
            status = record["status"]
            statuses[status] = statuses.get(status, 0) + 1
            if UrlStatus(status) in TERMINAL_STATUSES:
                terminal += 1
        exception_names = {
            UrlStatus.DOWNLOADED_INVALID.value,
            UrlStatus.EXCLUDED_BY_POLICY.value,
            UrlStatus.NOT_FOUND.value,
            UrlStatus.ACCESS_DENIED.value,
            UrlStatus.PERMANENT_ERROR.value,
            UrlStatus.UNRESOLVED_AFTER_RETRIES.value,
        }
        payload["summary"] = {
            "urls": len(urls),
            "terminal_urls": terminal,
            "documents": len(report.get("documents", [])),
            "assets": len(report.get("assets", [])),
            "asset_types": self._asset_counts(report.get("assets", [])),
            "exceptions": sum(count for status, count in statuses.items() if status in exception_names),
            "statuses": statuses,
        }
        payload["approval_gate"] = self._eligibility(payload)
        return payload

    @staticmethod
    def _asset_counts(assets: list[dict[str, object]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for asset in assets:
            kind = str(asset["kind"])
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def _path(self, run_id: str) -> Path:
        if not run_id or any(character not in "0123456789abcdef" for character in run_id):
            raise KeyError(run_id)
        return self.runs_dir / f"{run_id}.json"

    def _read_run(self, run_id: str) -> dict[str, object]:
        path = self._path(run_id)
        if not path.exists():
            raise KeyError(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_run(self, payload: dict[str, object]) -> None:
        with self._lock:
            _atomic_json(self._path(str(payload["id"])), payload)
