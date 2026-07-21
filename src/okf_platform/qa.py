"""Read-only adversarial coverage QA for a candidate crawl corpus."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import NotRequired, Protocol, TypedDict

from .models import AssetKind, CrawlReport, UrlStatus


class FindingSeverity(StrEnum):
    BLOCKER = "blocker"
    HIGH = "high"
    MEDIUM = "medium"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    tool: str
    urls: frozenset[str] = frozenset()
    status: str = "passed"
    error: str | None = None
    evidence: dict[str, object] = field(default_factory=dict)


class CoverageProbe(Protocol):
    name: str

    def inspect(self, target_url: str, allowed_hosts: tuple[str, ...]) -> ProbeResult: ...


@dataclass(frozen=True, slots=True)
class QaFinding:
    code: str
    severity: FindingSeverity
    message: str
    urls: tuple[str, ...] = ()


@dataclass(slots=True)
class QaReport:
    verdict: str
    probes: list[ProbeResult]
    findings: list[QaFinding]

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "probes": [
                {**asdict(probe), "urls": sorted(probe.urls)} for probe in self.probes
            ],
            "findings": [
                {**asdict(finding), "severity": finding.severity.value}
                for finding in self.findings
            ],
        }


class CoverageCritic:
    """Challenge crawler evidence without mutating the baseline or corpus store."""

    def evaluate(self, baseline: CrawlReport, probes: list[ProbeResult]) -> QaReport:
        findings: list[QaFinding] = []
        baseline_urls = set(baseline.urls)
        failed_discovery_tools = [
            str(item.get("tool"))
            for item in baseline.discovery_evidence
            if item.get("status") != "passed"
        ]
        if failed_discovery_tools:
            findings.append(
                QaFinding(
                    "DISCOVERY_TOOL_FAILED",
                    FindingSeverity.BLOCKER,
                    "Crawler evidence is incomplete because discovery tool(s) failed: "
                    + ", ".join(failed_discovery_tools),
                )
            )
        for probe in probes:
            if probe.status != "passed":
                findings.append(
                    QaFinding(
                        "QA_TOOL_FAILED",
                        FindingSeverity.BLOCKER,
                        f"Independent QA tool {probe.tool} failed: {probe.error or 'unknown error'}",
                    )
                )
                continue
            missing = sorted(probe.urls - baseline_urls)
            if missing:
                findings.append(
                    QaFinding(
                        "QA_ONLY_URLS",
                        FindingSeverity.BLOCKER,
                        f"{probe.tool} found {len(missing)} URL(s) absent from the crawler inventory",
                        tuple(missing[:100]),
                    )
                )

        unresolved = sorted(
            url
            for url, record in baseline.urls.items()
            if record.status
            in {
                UrlStatus.DOWNLOADED_INVALID,
                UrlStatus.ACCESS_DENIED,
                UrlStatus.PERMANENT_ERROR,
                UrlStatus.UNRESOLVED_AFTER_RETRIES,
            }
        )
        if unresolved:
            findings.append(
                QaFinding(
                    "UNRESOLVED_BASELINE",
                    FindingSeverity.BLOCKER,
                    f"Crawler has {len(unresolved)} invalid or unresolved outcome(s)",
                    tuple(unresolved[:100]),
                )
            )
        if baseline.budget_exhausted:
            findings.append(
                QaFinding("BUDGET_EXHAUSTED", FindingSeverity.BLOCKER, "Crawler budget was exhausted")
            )
        unknown = tuple(asset.url for asset in baseline.assets if asset.kind == AssetKind.OTHER)
        if unknown:
            findings.append(
                QaFinding(
                    "UNCLASSIFIED_ASSETS",
                    FindingSeverity.HIGH,
                    f"{len(unknown)} stored asset(s) require type review",
                    unknown[:100],
                )
            )
        if not baseline.assets:
            findings.append(
                QaFinding("EMPTY_CORPUS", FindingSeverity.BLOCKER, "No raw assets were stored")
            )
        unstored = tuple(asset.url for asset in baseline.assets if not asset.storage_uri)
        if unstored:
            findings.append(
                QaFinding(
                    "ASSETS_NOT_PERSISTED",
                    FindingSeverity.BLOCKER,
                    f"{len(unstored)} raw asset(s) lack a storage URI",
                    unstored[:100],
                )
            )
        stored_urls = {asset.url for asset in baseline.assets}
        missing_assets = tuple(
            url
            for url, record in baseline.urls.items()
            if record.status
            in {UrlStatus.PAGE_PROCESSED, UrlStatus.DOWNLOADED_VALID, UrlStatus.DUPLICATE_EXACT}
            and url not in stored_urls
        )
        if missing_assets:
            findings.append(
                QaFinding(
                    "TERMINAL_URL_WITHOUT_RAW_ASSET",
                    FindingSeverity.BLOCKER,
                    f"{len(missing_assets)} successful URL(s) have no stored raw object",
                    missing_assets[:100],
                )
            )
        blocker = any(item.severity == FindingSeverity.BLOCKER for item in findings)
        verdict = "fail" if blocker else "pass"
        if not findings:
            findings.append(
                QaFinding(
                    "QA_CLEAR",
                    FindingSeverity.INFO,
                    "Independent probes found no unexplained coverage gaps",
                )
            )
        return QaReport(verdict, probes, findings)


def run_qa(
    report: CrawlReport,
    target_url: str,
    allowed_hosts: tuple[str, ...],
    probes: list[CoverageProbe],
) -> QaReport:
    return CoverageCritic().evaluate(
        report,
        [probe.inspect(target_url, allowed_hosts) for probe in probes],
    )


class QaState(TypedDict):
    baseline: CrawlReport
    target_url: str
    allowed_hosts: tuple[str, ...]
    probe_results: NotRequired[list[ProbeResult]]
    qa_report: NotRequired[QaReport]


def build_qa_graph(probes: list[CoverageProbe]):
    """Build a QA-only LangGraph with no corpus mutation capability."""

    from langgraph.graph import END, START, StateGraph

    def probe_surfaces(state: QaState) -> QaState:
        return {
            **state,
            "probe_results": [
                probe.inspect(state["target_url"], state["allowed_hosts"]) for probe in probes
            ],
        }

    def critic(state: QaState) -> QaState:
        return {
            **state,
            "qa_report": CoverageCritic().evaluate(
                state["baseline"], state.get("probe_results", [])
            ),
        }

    graph = StateGraph(QaState)
    graph.add_node("independent_probes", probe_surfaces)
    graph.add_node("adversarial_critic", critic)
    graph.add_edge(START, "independent_probes")
    graph.add_edge("independent_probes", "adversarial_critic")
    graph.add_edge("adversarial_critic", END)
    return graph.compile()
