"""Shared, integrity-checked access to Stage 2 knowledge inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from .extraction import PIPELINE_VERSION, run_extraction
from .snapshot import canonical_hash, load_snapshot


def stable_id(prefix: str, *parts: object, length: int = 20) -> str:
    value = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}-{digest}"


def canonical_json_lines(records: Iterable[dict[str, object]]) -> str:
    return "".join(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    )


def load_extraction(
    data_dir: Path, corpus_id: str
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    """Load the frozen snapshot and verified extraction records for one corpus."""

    snapshot = load_snapshot(data_dir, corpus_id)
    manifest = run_extraction(data_dir, snapshot)
    extraction_dir = data_dir / "stage2" / corpus_id / PIPELINE_VERSION.replace("/", "-")
    records_path = extraction_dir / "records.jsonl"
    records_text = records_path.read_text(encoding="utf-8")
    if hashlib.sha256(records_text.encode("utf-8")).hexdigest() != manifest["records_sha256"]:
        raise ValueError("Stage 2 records failed integrity verification")
    records = [json.loads(line) for line in records_text.splitlines() if line.strip()]
    if len(records) != manifest["object_count"]:
        raise ValueError("Stage 2 record count does not match its manifest")
    return snapshot, manifest, records


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def verify_manifest(payload: dict[str, object]) -> None:
    expected = payload.get("manifest_sha256")
    core = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    if not expected or canonical_hash(core) != expected:
        raise ValueError("knowledge manifest failed integrity verification")
