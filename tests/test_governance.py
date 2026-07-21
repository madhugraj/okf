from __future__ import annotations

import pytest

from okf_platform.governance import assess_qa_exceptions, decorate_findings


def _report(code: str) -> dict[str, object]:
    return {
        "verdict": "fail",
        "findings": [
            {
                "code": code,
                "severity": "blocker",
                "message": "One controlled test finding",
                "urls": ["https://example.com/gap"],
            }
        ],
    }


def test_coverage_gap_requires_a_fingerprint_reason_and_residual_risk() -> None:
    report = _report("QA_ONLY_URLS")
    finding = decorate_findings(report)[0]
    assessment = assess_qa_exceptions(
        report,
        [
            {
                "finding_fingerprint": finding["fingerprint"],
                "accepted": True,
                "reason": "The extra URL is a decorative duplicate outside the knowledge scope.",
                "residual_risk": "A visual asset may remain absent.",
            }
        ],
        reviewer="Madhu",
    )
    assert not assessment["pending"]
    assert assessment["accepted"][0]["accepted_by"] == "Madhu"


def test_integrity_and_tool_failures_cannot_be_bypassed() -> None:
    report = _report("QA_TOOL_FAILED")
    finding = decorate_findings(report)[0]
    assessment = assess_qa_exceptions(report)
    assert assessment["hard"] == [finding]
    with pytest.raises(ValueError, match="does not match"):
        assess_qa_exceptions(
            report,
            [
                {
                    "finding_fingerprint": finding["fingerprint"],
                    "accepted": True,
                    "reason": "Attempting to accept a failed quality tool is not allowed.",
                    "residual_risk": "Coverage is unknown.",
                }
            ],
        )
