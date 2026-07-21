"""Compare two discovery runs without conflating convergence with completeness."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CrawlReport


@dataclass(frozen=True, slots=True)
class ConvergenceEvidence:
    new_urls: tuple[str, ...]
    missing_urls: tuple[str, ...]
    new_document_hashes: tuple[str, ...]

    @property
    def converged(self) -> bool:
        return not self.new_urls and not self.missing_urls and not self.new_document_hashes

    def to_dict(self) -> dict[str, object]:
        return {
            "converged": self.converged,
            "new_urls": list(self.new_urls),
            "missing_urls": list(self.missing_urls),
            "new_document_hashes": list(self.new_document_hashes),
        }


def compare_runs(previous: CrawlReport, current: CrawlReport) -> ConvergenceEvidence:
    previous_urls = set(previous.urls)
    current_urls = set(current.urls)
    previous_hashes = {document.sha256 for document in previous.documents}
    current_hashes = {document.sha256 for document in current.documents}
    return ConvergenceEvidence(
        new_urls=tuple(sorted(current_urls - previous_urls)),
        missing_urls=tuple(sorted(previous_urls - current_urls)),
        new_document_hashes=tuple(sorted(current_hashes - previous_hashes)),
    )
