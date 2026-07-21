"""Typed records shared by the deterministic crawler and LangGraph workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class UrlStatus(StrEnum):
    """Lifecycle states for a discovered URL."""

    QUEUED = "queued"
    FETCHING = "fetching"
    PAGE_PROCESSED = "page_processed"
    DOWNLOADED_VALID = "downloaded_valid"
    DOWNLOADED_INVALID = "downloaded_invalid"
    EXCLUDED_BY_POLICY = "excluded_by_policy"
    DUPLICATE_EXACT = "duplicate_exact"
    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"
    PERMANENT_ERROR = "permanent_error"
    UNRESOLVED_AFTER_RETRIES = "unresolved_after_retries"


TERMINAL_STATUSES = frozenset(
    {
        UrlStatus.PAGE_PROCESSED,
        UrlStatus.DOWNLOADED_VALID,
        UrlStatus.DOWNLOADED_INVALID,
        UrlStatus.EXCLUDED_BY_POLICY,
        UrlStatus.DUPLICATE_EXACT,
        UrlStatus.NOT_FOUND,
        UrlStatus.ACCESS_DENIED,
        UrlStatus.PERMANENT_ERROR,
        UrlStatus.UNRESOLVED_AFTER_RETRIES,
    }
)


@dataclass(slots=True)
class FetchResponse:
    """Transport-neutral HTTP response used by crawl mechanics and tests."""

    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: int = 0

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";", 1)[0].strip().lower()


@dataclass(slots=True)
class UrlRecord:
    """Auditable terminal or transient state for one canonical URL."""

    url: str
    referring_url: str | None
    discovery_method: str
    depth: int
    status: UrlStatus = UrlStatus.QUEUED
    http_status: int | None = None
    reason: str | None = None
    content_type: str | None = None


@dataclass(slots=True)
class DocumentRecord:
    """Integrity and provenance evidence for a downloaded PDF."""

    url: str
    referring_url: str | None
    filename: str
    byte_size: int
    sha256: str
    valid_pdf: bool
    page_count: int | None
    validation_error: str | None = None
    duplicate_of: str | None = None


@dataclass(slots=True)
class CrawlReport:
    """Serializable evidence bundle for a bounded discovery run."""

    target_url: str
    urls: dict[str, UrlRecord] = field(default_factory=dict)
    documents: list[DocumentRecord] = field(default_factory=list)
    discovered_edges: list[tuple[str, str]] = field(default_factory=list)
    budget_exhausted: bool = False

    @property
    def ready_for_reconciliation(self) -> bool:
        return bool(self.urls) and all(record.status in TERMINAL_STATUSES for record in self.urls.values())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["urls"] = {
            url: {**asdict(record), "status": record.status.value}
            for url, record in self.urls.items()
        }
        payload["ready_for_reconciliation"] = self.ready_for_reconciliation
        return payload
