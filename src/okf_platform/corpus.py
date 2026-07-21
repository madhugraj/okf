"""Typed, content-addressed storage for raw crawl assets and provenance."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import mimetypes
from pathlib import Path, PurePosixPath
import sqlite3
from threading import RLock
from urllib.parse import unquote, urlsplit

from .models import AssetKind, AssetRecord, FetchResponse


MIME_KIND: dict[str, tuple[AssetKind, str]] = {
    "application/pdf": (AssetKind.PDF, ".pdf"),
    "text/html": (AssetKind.HTML, ".html"),
    "application/xhtml+xml": (AssetKind.HTML, ".html"),
    "text/css": (AssetKind.CODE, ".css"),
    "text/javascript": (AssetKind.CODE, ".js"),
    "application/javascript": (AssetKind.CODE, ".js"),
    "application/json": (AssetKind.STRUCTURED_DATA, ".json"),
    "application/xml": (AssetKind.STRUCTURED_DATA, ".xml"),
    "text/xml": (AssetKind.STRUCTURED_DATA, ".xml"),
    "text/csv": (AssetKind.STRUCTURED_DATA, ".csv"),
    "application/zip": (AssetKind.ARCHIVE, ".zip"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        AssetKind.OFFICE,
        ".docx",
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        AssetKind.OFFICE,
        ".xlsx",
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        AssetKind.OFFICE,
        ".pptx",
    ),
}

CODE_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".css", ".go", ".h", ".html", ".java", ".js", ".jsx",
    ".kt", ".php", ".py", ".rb", ".rs", ".sh", ".sql", ".ts", ".tsx", ".vue",
}
OFFICE_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt"}
ARCHIVE_EXTENSIONS = {".7z", ".bz2", ".gz", ".rar", ".tar", ".tgz", ".zip"}


def _extension(url: str, mime_type: str) -> str:
    suffix = PurePosixPath(unquote(urlsplit(url).path)).suffix.lower()
    if suffix and len(suffix) <= 12 and suffix[1:].replace("-", "").isalnum():
        return suffix
    return MIME_KIND.get(mime_type, (AssetKind.OTHER, mimetypes.guess_extension(mime_type) or ".bin"))[1]


def classify_asset(url: str, declared_mime: str, body: bytes) -> tuple[AssetKind, str, str]:
    """Classify an asset using magic bytes, MIME type and URL extension, in that order."""

    mime_type = declared_mime.split(";", 1)[0].strip().lower()
    extension = _extension(url, mime_type)
    if body.startswith(b"%PDF-"):
        return AssetKind.PDF, ".pdf", "application/pdf"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return AssetKind.IMAGE, ".png", "image/png"
    if body.startswith((b"\xff\xd8\xff",)):
        return AssetKind.IMAGE, ".jpg", "image/jpeg"
    if len(body) >= 12 and body[4:8] == b"ftyp":
        return AssetKind.VIDEO, extension if extension != ".bin" else ".mp4", mime_type or "video/mp4"
    if mime_type in MIME_KIND:
        kind, default_extension = MIME_KIND[mime_type]
        return kind, extension if extension != ".bin" else default_extension, mime_type
    if mime_type.startswith("image/"):
        return AssetKind.IMAGE, extension, mime_type
    if mime_type.startswith("video/"):
        return AssetKind.VIDEO, extension, mime_type
    if mime_type.startswith("audio/"):
        return AssetKind.AUDIO, extension, mime_type
    if extension in CODE_EXTENSIONS or mime_type.startswith("text/"):
        return AssetKind.CODE, extension, mime_type or "text/plain"
    if extension in OFFICE_EXTENSIONS:
        return AssetKind.OFFICE, extension, mime_type or "application/octet-stream"
    if extension in ARCHIVE_EXTENSIONS:
        return AssetKind.ARCHIVE, extension, mime_type or "application/octet-stream"
    return AssetKind.OTHER, extension, mime_type or "application/octet-stream"


class LocalCorpusStore:
    """Store immutable raw bytes on disk and provenance observations in SQLite.

    The object layout mirrors the key layout intended for S3/MinIO. SHA-256 makes writes
    idempotent and deduplicates identical bytes without losing source observations.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects_dir = root / "objects"
        self.database_path = root / "metadata.sqlite3"
        self._lock = RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def save(
        self,
        run_id: str,
        response: FetchResponse,
        *,
        referring_url: str | None,
        discovered_by: str,
    ) -> AssetRecord:
        kind, extension, detected_mime = classify_asset(
            response.final_url, response.content_type, response.body
        )
        sha256 = hashlib.sha256(response.body).hexdigest()
        relative = Path(kind.value) / sha256[:2] / f"{sha256}{extension}"
        destination = self.objects_dir / relative
        with self._lock:
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(destination.suffix + ".tmp")
                temporary.write_bytes(response.body)
                temporary.replace(destination)
            saved_at = datetime.now(timezone.utc).isoformat()
            record = AssetRecord(
                url=response.requested_url,
                final_url=response.final_url,
                referring_url=referring_url,
                kind=kind,
                filename=PurePosixPath(unquote(urlsplit(response.final_url).path)).name
                or f"index{extension}",
                extension=extension,
                declared_mime=response.content_type or None,
                detected_mime=detected_mime,
                byte_size=len(response.body),
                sha256=sha256,
                storage_uri=f"corpus://objects/{relative.as_posix()}",
                discovered_by=discovered_by,
                saved_at=saved_at,
            )
            self._record(run_id, record)
        return record

    def counts(self, run_id: str) -> dict[str, int]:
        with sqlite3.connect(self.database_path) as database:
            rows = database.execute(
                "SELECT kind, COUNT(*) FROM observations WHERE run_id = ? GROUP BY kind",
                (run_id,),
            ).fetchall()
        return {kind: count for kind, count in rows}

    def _initialise(self) -> None:
        with sqlite3.connect(self.database_path) as database:
            database.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS objects (
                    sha256 TEXT PRIMARY KEY, kind TEXT NOT NULL, byte_size INTEGER NOT NULL,
                    storage_uri TEXT NOT NULL, detected_mime TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, url TEXT NOT NULL,
                    final_url TEXT NOT NULL, referring_url TEXT, sha256 TEXT NOT NULL,
                    kind TEXT NOT NULL, filename TEXT NOT NULL, extension TEXT NOT NULL,
                    declared_mime TEXT, discovered_by TEXT NOT NULL, saved_at TEXT NOT NULL,
                    UNIQUE(run_id, url, sha256, discovered_by, referring_url),
                    FOREIGN KEY(sha256) REFERENCES objects(sha256)
                );
                CREATE INDEX IF NOT EXISTS idx_observations_run ON observations(run_id);
                """
            )

    def _record(self, run_id: str, record: AssetRecord) -> None:
        payload = asdict(record)
        with sqlite3.connect(self.database_path) as database:
            database.execute(
                "INSERT OR IGNORE INTO objects VALUES (?, ?, ?, ?, ?)",
                (
                    record.sha256,
                    record.kind.value,
                    record.byte_size,
                    record.storage_uri,
                    record.detected_mime,
                ),
            )
            database.execute(
                """INSERT OR IGNORE INTO observations
                   (run_id, url, final_url, referring_url, sha256, kind, filename, extension,
                    declared_mime, discovered_by, saved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    payload["url"],
                    payload["final_url"],
                    payload["referring_url"],
                    payload["sha256"],
                    record.kind.value,
                    payload["filename"],
                    payload["extension"],
                    payload["declared_mime"],
                    payload["discovered_by"],
                    payload["saved_at"],
                ),
            )
