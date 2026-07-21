"""Deterministic URL canonicalisation, scope enforcement, and SSRF controls."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


class PolicyViolation(ValueError):
    """Raised when a URL violates the configured crawl boundary."""


@dataclass(frozen=True, slots=True)
class CrawlPolicy:
    allowed_hosts: tuple[str, ...]
    allow_subdomains: bool = False
    max_depth: int = 6
    max_pages: int = 500
    max_download_bytes: int = 50 * 1024 * 1024
    max_redirects: int = 5
    timeout_seconds: float = 20.0
    user_agent: str = "OKF-AuditableCrawler/0.1 (+https://github.com/madhugraj/okf)"

    def __post_init__(self) -> None:
        normalised = tuple(_normalise_host(host) for host in self.allowed_hosts)
        if not normalised:
            raise ValueError("at least one allowed host is required")
        object.__setattr__(self, "allowed_hosts", normalised)
        if self.max_depth < 0 or self.max_pages < 1 or self.max_download_bytes < 1:
            raise ValueError("crawl budgets must be positive")


def _normalise_host(host: str) -> str:
    return host.rstrip(".").lower().encode("idna").decode("ascii")


def canonicalise_url(url: str, *, base_url: str | None = None) -> str:
    """Return a stable HTTP(S) URL without credentials or fragments."""

    absolute = urljoin(base_url, url) if base_url else url
    parts = urlsplit(absolute)
    if parts.scheme.lower() not in {"http", "https"}:
        raise PolicyViolation("only http and https URLs are allowed")
    if not parts.hostname:
        raise PolicyViolation("URL must include a hostname")
    if parts.username or parts.password:
        raise PolicyViolation("URL credentials are not allowed")

    host = _normalise_host(parts.hostname)
    port = parts.port
    display_host = f"[{host}]" if ":" in host else host
    if port and not ((parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443)):
        netloc = f"{display_host}:{port}"
    else:
        netloc = display_host
    path = parts.path or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)), doseq=True)
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def ensure_in_scope(url: str, policy: CrawlPolicy) -> str:
    canonical = canonicalise_url(url)
    host = urlsplit(canonical).hostname or ""
    allowed = host in policy.allowed_hosts
    if policy.allow_subdomains:
        allowed = allowed or any(host.endswith(f".{root}") for root in policy.allowed_hosts)
    if not allowed:
        raise PolicyViolation(f"host {host!r} is outside the allowed scope")
    _reject_literal_unsafe_address(host)
    return canonical


def ensure_public_dns(host: str) -> None:
    """Reject hosts resolving to non-public addresses immediately before a request."""

    _reject_literal_unsafe_address(host)
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise PolicyViolation(f"DNS resolution failed for {host!r}") from exc
    if not addresses:
        raise PolicyViolation(f"DNS returned no addresses for {host!r}")
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise PolicyViolation(f"host {host!r} resolves to non-public address")


def _reject_literal_unsafe_address(host: str) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise PolicyViolation("non-public IP addresses are not allowed")
