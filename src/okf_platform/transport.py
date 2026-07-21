"""Bounded public-HTTP transport with redirect and response-size controls."""

from __future__ import annotations

import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlsplit

from .models import FetchResponse
from .policy import CrawlPolicy, PolicyViolation, ensure_in_scope, ensure_public_dns


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class HttpTransport:
    """A small transport kept separate so fixture tests need no external network."""

    def __init__(self, policy: CrawlPolicy) -> None:
        self.policy = policy
        self._opener = build_opener(_NoRedirect)

    def fetch(self, url: str) -> FetchResponse:
        current = ensure_in_scope(url, self.policy)
        started = time.monotonic()
        for _ in range(self.policy.max_redirects + 1):
            host = urlsplit(current).hostname or ""
            ensure_public_dns(host)
            request = Request(
                current,
                headers={"User-Agent": self.policy.user_agent, "Accept": "text/html,application/pdf,application/xml;q=0.9,*/*;q=0.1"},
            )
            try:
                response = self._opener.open(request, timeout=self.policy.timeout_seconds)
            except HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                    from .policy import canonicalise_url

                    current = ensure_in_scope(canonicalise_url(exc.headers["Location"], base_url=current), self.policy)
                    continue
                body = exc.read(min(self.policy.max_download_bytes, 64 * 1024))
                return FetchResponse(url, current, exc.code, {k.lower(): v for k, v in exc.headers.items()}, body)

            declared = response.headers.get("Content-Length")
            if declared and int(declared) > self.policy.max_download_bytes:
                raise PolicyViolation("response exceeds configured byte budget")
            body = response.read(self.policy.max_download_bytes + 1)
            if len(body) > self.policy.max_download_bytes:
                raise PolicyViolation("response exceeds configured byte budget")
            return FetchResponse(
                url,
                current,
                response.status,
                {k.lower(): v for k, v in response.headers.items()},
                body,
                round((time.monotonic() - started) * 1000),
            )
        raise PolicyViolation("redirect limit exceeded")
