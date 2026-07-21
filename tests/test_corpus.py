from __future__ import annotations

import sqlite3

from okf_platform.corpus import LocalCorpusStore, classify_asset
from okf_platform.models import AssetKind, FetchResponse


def _response(url: str, content_type: str, body: bytes) -> FetchResponse:
    return FetchResponse(url, url, 200, {"content-type": content_type}, body)


def test_asset_classification_distinguishes_corpus_types() -> None:
    assert classify_asset("https://e.test/a.pdf", "text/plain", b"%PDF-1.7\n")[0] == AssetKind.PDF
    assert classify_asset("https://e.test/a.png", "", b"\x89PNG\r\n\x1a\nrest")[0] == AssetKind.IMAGE
    assert classify_asset("https://e.test/a.mp4", "video/mp4", b"\x00\x00\x00\x18ftypmp42")[0] == AssetKind.VIDEO
    assert classify_asset("https://e.test/a.js", "application/javascript", b"let x=1")[0] == AssetKind.CODE
    assert classify_asset("https://e.test/a.xlsx", "application/octet-stream", b"PK")[0] == AssetKind.OFFICE


def test_local_corpus_store_deduplicates_bytes_but_preserves_observations(tmp_path) -> None:
    store = LocalCorpusStore(tmp_path)
    body = b"%PDF-1.7\nfixture"
    first = store.save(
        "run1",
        _response("https://e.test/a.pdf", "application/pdf", body),
        referring_url="https://e.test/one",
        discovered_by="crawler:http",
    )
    second = store.save(
        "run1",
        _response("https://e.test/b.pdf", "application/pdf", body),
        referring_url="https://e.test/two",
        discovered_by="crawler:sitemap",
    )

    assert first.storage_uri == second.storage_uri
    assert len(list((tmp_path / "objects" / "pdf").rglob("*.pdf"))) == 1
    assert store.counts("run1") == {"pdf": 2}
    with sqlite3.connect(tmp_path / "metadata.sqlite3") as database:
        assert database.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
