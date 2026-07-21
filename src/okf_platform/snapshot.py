"""Immutable approved-corpus manifests used as the Stage 2 input contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def resolve_corpus_uri(data_dir: Path, storage_uri: str) -> Path:
    prefix = "corpus://"
    if not storage_uri.startswith(prefix):
        raise ValueError(f"unsupported storage URI: {storage_uri}")
    relative = Path(storage_uri[len(prefix) :])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe storage URI: {storage_uri}")
    return data_dir / "corpus" / relative


def freeze_corpus_snapshot(
    data_dir: Path,
    approval: dict[str, object],
    report: dict[str, object],
) -> dict[str, object]:
    """Verify raw objects and freeze objects plus all source observations."""

    observations = [dict(item) for item in report.get("assets", [])]
    if not observations:
        raise ValueError("cannot freeze an empty corpus")
    objects: dict[str, dict[str, object]] = {}
    for item in observations:
        sha256 = str(item.get("sha256", ""))
        storage_uri = str(item.get("storage_uri", ""))
        if len(sha256) != 64 or not storage_uri:
            raise ValueError(f"asset {item.get('url')} has incomplete storage evidence")
        path = resolve_corpus_uri(data_dir, storage_uri)
        if not path.is_file():
            raise ValueError(f"stored corpus object is missing: {storage_uri}")
        with path.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != sha256:
            raise ValueError(f"stored corpus object failed hash verification: {storage_uri}")
        candidate = {
            "sha256": sha256,
            "kind": item["kind"],
            "byte_size": item["byte_size"],
            "detected_mime": item["detected_mime"],
            "extension": item["extension"],
            "storage_uri": storage_uri,
        }
        previous = objects.setdefault(sha256, candidate)
        if previous != candidate:
            raise ValueError(f"conflicting metadata for corpus object {sha256}")

    core: dict[str, object] = {
        "schema_version": "okf-corpus-snapshot/1.0",
        "corpus_id": approval["id"],
        "target_url": approval["target_url"],
        "source_run_id": approval["run_id"],
        "baseline_run_id": approval["baseline_run_id"],
        "approved_at": approval["approved_at"],
        "approved_by": approval["reviewer"],
        "crawl_report_sha256": approval["report_sha256"],
        "qa_effective_verdict": approval["qa_effective_verdict"],
        "accepted_qa_exceptions": approval["accepted_qa_exceptions"],
        "objects": sorted(objects.values(), key=lambda item: str(item["sha256"])),
        "observations": sorted(
            observations,
            key=lambda item: (
                str(item.get("sha256")),
                str(item.get("url")),
                str(item.get("discovered_by")),
            ),
        ),
    }
    manifest = {**core, "manifest_sha256": canonical_hash(core)}
    destination = data_dir / "corpora" / str(approval["id"]) / "manifest.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return {
        "uri": f"corpus-snapshot://{approval['id']}/manifest.json",
        "manifest_sha256": manifest["manifest_sha256"],
        "object_count": len(objects),
        "observation_count": len(observations),
    }


def load_snapshot(data_dir: Path, corpus_id: str) -> dict[str, object]:
    if not corpus_id.startswith("corpus-") or not corpus_id[7:].isalnum():
        raise KeyError(corpus_id)
    path = data_dir / "corpora" / corpus_id / "manifest.json"
    if not path.is_file():
        raise KeyError(corpus_id)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected = manifest.pop("manifest_sha256")
    actual = canonical_hash(manifest)
    manifest["manifest_sha256"] = expected
    if expected != actual:
        raise ValueError("corpus snapshot manifest failed integrity verification")
    return manifest
