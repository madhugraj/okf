"""Audited human acceptance of bounded QA coverage gaps."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Iterable


WAIVABLE_QA_CODES = frozenset({"QA_ONLY_URLS", "UNRESOLVED_BASELINE"})


def finding_fingerprint(finding: dict[str, object]) -> str:
    """Bind an exception to the exact critic finding the reviewer saw."""

    evidence = {
        "code": finding.get("code"),
        "severity": finding.get("severity"),
        "message": finding.get("message"),
        "urls": sorted(str(url) for url in finding.get("urls", [])),
    }
    return hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def decorate_findings(report: dict[str, object] | None) -> list[dict[str, object]]:
    if not report:
        return []
    decorated: list[dict[str, object]] = []
    for item in report.get("findings", []):
        finding = dict(item)
        finding["fingerprint"] = finding_fingerprint(finding)
        finding["waivable"] = (
            finding.get("severity") == "blocker"
            and finding.get("code") in WAIVABLE_QA_CODES
        )
        decorated.append(finding)
    return decorated


def assess_qa_exceptions(
    report: dict[str, object] | None,
    requested: Iterable[dict[str, object]] = (),
    *,
    reviewer: str | None = None,
) -> dict[str, object]:
    """Validate explicit exceptions and separate residual gaps from hard blockers."""

    blockers = [item for item in decorate_findings(report) if item["severity"] == "blocker"]
    proposals = {str(item.get("finding_fingerprint")): dict(item) for item in requested}
    accepted: list[dict[str, object]] = []
    pending: list[dict[str, object]] = []
    hard: list[dict[str, object]] = []

    for finding in blockers:
        if not finding["waivable"]:
            hard.append(finding)
            continue
        proposal = proposals.get(str(finding["fingerprint"]))
        if proposal is None:
            pending.append(finding)
            continue
        reason = str(proposal.get("reason", "")).strip()
        residual_risk = str(proposal.get("residual_risk", "")).strip()
        if proposal.get("accepted") is not True:
            raise ValueError(f"exception {finding['code']} was not explicitly accepted")
        if len(reason) < 20:
            raise ValueError(f"exception {finding['code']} requires a reason of at least 20 characters")
        if len(residual_risk) < 10:
            raise ValueError(
                f"exception {finding['code']} requires a residual-risk note of at least 10 characters"
            )
        accepted.append(
            {
                "finding_fingerprint": finding["fingerprint"],
                "code": finding["code"],
                "message": finding["message"],
                "urls": list(finding.get("urls", [])),
                "reason": reason,
                "residual_risk": residual_risk,
                "accepted_by": reviewer,
                "accepted_at": datetime.now(timezone.utc).isoformat() if reviewer else None,
            }
        )

    known = {str(item["fingerprint"]) for item in blockers if item["waivable"]}
    unknown = sorted(key for key in proposals if key not in known)
    if unknown:
        raise ValueError("an exception does not match the current QA evidence")
    return {"accepted": accepted, "pending": pending, "hard": hard}
