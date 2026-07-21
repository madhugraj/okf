"""Deterministic Stage 2 extraction over a frozen, approved corpus."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
from xml.etree import ElementTree
import zipfile

import fitz

from .snapshot import canonical_hash, resolve_corpus_uri


PIPELINE_VERSION = "typed-extraction/1.0"
TEXT_KINDS = frozenset({"code", "structured_data"})
BINARY_KINDS = frozenset({"image", "video", "audio", "archive", "other"})


class _VisibleHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        elif not self.hidden and tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in {"p", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        return _normalise_text(" ".join(self.parts))


def _normalise_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "").split("\n")]
    return "\n".join(line for line in lines if line)


def _chunk_units(text: str, sha256: str, *, locator: dict[str, object]) -> list[dict[str, object]]:
    text = _normalise_text(text)
    if not text:
        return []
    units: list[dict[str, object]] = []
    start = 0
    sequence = 1
    while start < len(text):
        end = min(len(text), start + 2_000)
        if end < len(text):
            boundary = text.rfind("\n", start, end)
            if boundary > start + 400:
                end = boundary
        value = text[start:end].strip()
        if value:
            unit_locator = {**locator, "char_start": start, "char_end": end}
            units.append(
                {
                    "unit_id": f"unit-{sha256[:12]}-{sequence:05d}",
                    "sequence": sequence,
                    "text": value,
                    "locator": unit_locator,
                }
            )
            sequence += 1
        start = max(end, start + 1)
    return units


def _pdf_units(data: bytes, sha256: str) -> list[dict[str, object]]:
    units: list[dict[str, object]] = []
    with fitz.open(stream=data, filetype="pdf") as document:
        for page_number, page in enumerate(document, start=1):
            page_units = _chunk_units(
                page.get_text("text"), sha256, locator={"type": "pdf_page", "page": page_number}
            )
            for item in page_units:
                item["unit_id"] = f"unit-{sha256[:12]}-p{page_number:04d}-{item['sequence']:03d}"
                item["sequence"] = len(units) + 1
            units.extend(page_units)
    return units


def _openxml_text(data: bytes) -> str:
    values: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = sorted(
            name
            for name in archive.namelist()
            if name.endswith(".xml")
            and name.startswith(("word/", "ppt/slides/", "xl/sharedStrings"))
        )
        for name in members:
            root = ElementTree.fromstring(archive.read(name))
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] == "t" and node.text:
                    values.append(node.text)
            values.append("\n")
    return _normalise_text(" ".join(values))


def extract_object(
    data: bytes,
    item: dict[str, object],
    source_urls: list[str],
) -> dict[str, object]:
    """Extract one immutable object without changing or enriching the raw corpus."""

    sha256 = str(item["sha256"])
    kind = str(item["kind"])
    extension = str(item.get("extension", ""))
    adapter = "none"
    units: list[dict[str, object]] = []
    status = "extracted"
    reason: str | None = None
    try:
        if kind == "pdf":
            adapter = "pymupdf_page_text"
            units = _pdf_units(data, sha256)
        elif kind == "html":
            adapter = "stdlib_visible_html"
            parser = _VisibleHtml()
            parser.feed(data.decode("utf-8", errors="replace"))
            units = _chunk_units(parser.text(), sha256, locator={"type": "html_text"})
        elif kind in TEXT_KINDS:
            adapter = "utf8_text"
            units = _chunk_units(
                data.decode("utf-8", errors="replace"), sha256, locator={"type": "text_span"}
            )
        elif kind == "office" and extension in {".docx", ".pptx", ".xlsx"}:
            adapter = "openxml_text"
            units = _chunk_units(_openxml_text(data), sha256, locator={"type": "office_text"})
        elif kind == "office":
            status, reason = "not_extractable", "legacy Office adapter is not configured"
        elif kind in BINARY_KINDS:
            status, reason = "not_extractable", f"{kind} extraction adapter is not configured"
        else:
            status, reason = "not_extractable", f"no adapter for asset kind {kind}"
        if status == "extracted" and not units:
            status, reason = "empty_text", "adapter completed but returned no text"
    except Exception as exc:
        status = "failed"
        reason = f"{type(exc).__name__}: {exc}"
    return {
        "object_sha256": sha256,
        "kind": kind,
        "detected_mime": item["detected_mime"],
        "storage_uri": item["storage_uri"],
        "source_urls": source_urls,
        "status": status,
        "adapter": adapter,
        "reason": reason,
        "units": units,
    }


def run_extraction(data_dir: Path, snapshot: dict[str, object]) -> dict[str, object]:
    corpus_id = str(snapshot["corpus_id"])
    output_dir = data_dir / "stage2" / corpus_id / PIPELINE_VERSION.replace("/", "-")
    manifest_path = output_dir / "manifest.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("corpus_manifest_sha256") == snapshot["manifest_sha256"]:
            return existing

    urls_by_hash: dict[str, set[str]] = {}
    for observation in snapshot["observations"]:
        urls_by_hash.setdefault(str(observation["sha256"]), set()).add(str(observation["url"]))
    records = []
    for item in snapshot["objects"]:
        path = resolve_corpus_uri(data_dir, str(item["storage_uri"]))
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"raw corpus object changed after approval: {item['storage_uri']}")
        records.append(extract_object(data, item, sorted(urls_by_hash[item["sha256"]])))
    records.sort(key=lambda item: str(item["object_sha256"]))

    records_text = "".join(
        json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in records
    )
    records_sha256 = hashlib.sha256(records_text.encode("utf-8")).hexdigest()
    status_counts = Counter(str(item["status"]) for item in records)
    kind_counts = Counter(str(item["kind"]) for item in records)
    core: dict[str, object] = {
        "schema_version": "okf-typed-extraction/1.0",
        "pipeline_version": PIPELINE_VERSION,
        "corpus_id": corpus_id,
        "corpus_manifest_sha256": snapshot["manifest_sha256"],
        "records_sha256": records_sha256,
        "object_count": len(records),
        "text_unit_count": sum(len(item["units"]) for item in records),
        "status_counts": dict(sorted(status_counts.items())),
        "kind_counts": dict(sorted(kind_counts.items())),
        "records_uri": f"stage2://{corpus_id}/{PIPELINE_VERSION}/records.jsonl",
    }
    manifest = {
        **core,
        "extraction_id": f"extract-{records_sha256[:16]}",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": canonical_hash(core),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    records_tmp = output_dir / "records.jsonl.tmp"
    records_tmp.write_text(records_text, encoding="utf-8")
    records_tmp.replace(output_dir / "records.jsonl")
    manifest_tmp = output_dir / "manifest.json.tmp"
    manifest_tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest_tmp.replace(manifest_path)
    return manifest
