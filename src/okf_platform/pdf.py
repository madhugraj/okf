"""PDF integrity validation and content hashing."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO


@dataclass(frozen=True, slots=True)
class PdfEvidence:
    sha256: str
    byte_size: int
    valid: bool
    page_count: int | None
    error: str | None = None


def validate_pdf(content: bytes) -> PdfEvidence:
    digest = sha256(content).hexdigest()
    if not content.startswith(b"%PDF-"):
        return PdfEvidence(digest, len(content), False, None, "missing PDF signature")
    if b"%%EOF" not in content[-2048:]:
        return PdfEvidence(digest, len(content), False, None, "missing PDF end marker")

    try:
        import pymupdf

        with pymupdf.open(stream=BytesIO(content), filetype="pdf") as document:
            pages = document.page_count
            if pages < 1:
                return PdfEvidence(digest, len(content), False, pages, "PDF contains no pages")
            return PdfEvidence(digest, len(content), True, pages)
    except ImportError:
        return PdfEvidence(digest, len(content), True, None)
    except Exception as exc:  # PyMuPDF exposes several parser-specific exception types.
        return PdfEvidence(digest, len(content), False, None, f"PDF parse failed: {type(exc).__name__}")
