from __future__ import annotations

from dataclasses import asdict

import pytest

from okf_platform.corpus import LocalCorpusStore
from okf_platform.extraction import run_extraction
from okf_platform.models import FetchResponse
from okf_platform.snapshot import resolve_corpus_uri


def _save(store: LocalCorpusStore, url: str, mime: str, body: bytes):
    return store.save(
        "run1",
        FetchResponse(url, url, 200, {"content-type": mime}, body),
        referring_url="https://example.com/",
        discovered_by="test",
    )


def test_stage2_extracts_text_and_keeps_unconfigured_binary_types_visible(tmp_path) -> None:
    store = LocalCorpusStore(tmp_path / "corpus")
    html = _save(
        store,
        "https://example.com/index.html",
        "text/html",
        b"<h1>Services</h1><script>ignore()</script><p>Ground handling</p>",
    )
    code = _save(
        store,
        "https://example.com/app.js",
        "application/javascript",
        b"const service = 'cargo';",
    )
    image = _save(
        store,
        "https://example.com/logo.png",
        "image/png",
        b"\x89PNG\r\n\x1a\nfixture",
    )
    assets = [html, code, image]
    snapshot = {
        "corpus_id": "corpus-fixture",
        "manifest_sha256": "f" * 64,
        "objects": [
            {
                key: value.value if hasattr(value, "value") else value
                for key, value in asdict(asset).items()
                if key
                in {
                    "sha256",
                    "kind",
                    "byte_size",
                    "detected_mime",
                    "extension",
                    "storage_uri",
                }
            }
            for asset in assets
        ],
        "observations": [
            {**asdict(asset), "kind": asset.kind.value} for asset in assets
        ],
    }
    manifest = run_extraction(tmp_path, snapshot)
    assert manifest["object_count"] == 3
    assert manifest["status_counts"] == {"extracted": 2, "not_extractable": 1}
    records = (tmp_path / "stage2" / "corpus-fixture" / "typed-extraction-1.0" / "records.jsonl").read_text()
    assert "Ground handling" in records
    assert "ignore()" not in records
    assert "image extraction adapter is not configured" in records


def test_stage2_rejects_raw_object_changed_after_approval(tmp_path) -> None:
    store = LocalCorpusStore(tmp_path / "corpus")
    asset = _save(store, "https://example.com/a.js", "application/javascript", b"const a=1;")
    item = {
        key: value.value if hasattr(value, "value") else value
        for key, value in asdict(asset).items()
        if key
        in {
            "sha256",
            "kind",
            "byte_size",
            "detected_mime",
            "extension",
            "storage_uri",
        }
    }
    resolve_corpus_uri(tmp_path, asset.storage_uri).write_bytes(b"tampered")
    snapshot = {
        "corpus_id": "corpus-tampered",
        "manifest_sha256": "a" * 64,
        "objects": [item],
        "observations": [{**asdict(asset), "kind": asset.kind.value}],
    }
    with pytest.raises(ValueError, match="changed after approval"):
        run_extraction(tmp_path, snapshot)
