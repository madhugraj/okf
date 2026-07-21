"""Atomic JSON persistence for crawl checkpoints."""

from __future__ import annotations

import json
from pathlib import Path

from .models import CrawlReport


def save_report(report: CrawlReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    temporary.replace(path)


def load_report(path: Path) -> CrawlReport:
    return CrawlReport.from_dict(json.loads(path.read_text(encoding="utf-8")))
