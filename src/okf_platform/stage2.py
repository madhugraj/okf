"""Application service for approved-corpus Stage 2 processing."""

from __future__ import annotations

from pathlib import Path

from .extraction import run_extraction
from .snapshot import load_snapshot


class Stage2Service:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def extract(self, corpus_id: str) -> dict[str, object]:
        snapshot = load_snapshot(self.data_dir, corpus_id)
        return run_extraction(self.data_dir, snapshot)
