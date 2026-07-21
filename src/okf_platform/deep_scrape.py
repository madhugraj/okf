"""Independent deep-discovery adapters used by crawler and QA workflows."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin, urlsplit

from .policy import canonicalise_url, ensure_public_dns
from .qa import ProbeResult


@dataclass(slots=True)
class BrowserDeepScraper:
    """Rendered-DOM and browser-network discovery using Playwright.

    It deliberately performs only GET navigation, scrolling and DOM inspection. It never submits
    forms or clicks actions because the crawler must remain non-mutating.
    """

    max_pages: int = 50
    scroll_rounds: int = 3
    name: str = "playwright_rendered_dom_and_network"
    rendered_html: dict[str, bytes] = field(default_factory=dict)
    url_filter: Callable[[str], bool] = lambda _: True

    def inspect(self, target_url: str, allowed_hosts: tuple[str, ...]) -> ProbeResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ProbeResult(self.name, status="failed", error="Playwright is not installed")

        discovered: set[str] = set()
        queued = deque([canonicalise_url(target_url)])
        visited: set[str] = set()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(service_workers="block")

                def scope_route(route) -> None:
                    if self._in_scope(route.request.url, allowed_hosts):
                        route.continue_()
                    else:
                        route.abort("blockedbyclient")

                context.route("**/*", scope_route)
                page = context.new_page()

                def record_response(response) -> None:
                    self._add(response.url, allowed_hosts, discovered)

                page.on("response", record_response)
                while queued and len(visited) < self.max_pages:
                    url = queued.popleft()
                    if url in visited:
                        continue
                    visited.add(url)
                    ensure_public_dns(urlsplit(url).hostname or "")
                    page.goto(url, wait_until="networkidle", timeout=45_000)
                    for _ in range(self.scroll_rounds):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(300)
                    self.rendered_html[url] = page.content().encode("utf-8")
                    candidates = page.locator("a[href],link[href],img[src],script[src],source[src],video[src]").evaluate_all(
                        "els => els.map(e => e.href || e.src).filter(Boolean)"
                    )
                    for candidate in candidates:
                        if self._add(candidate, allowed_hosts, discovered):
                            parsed = urlsplit(candidate)
                            if not parsed.path.lower().endswith(
                                (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".mp4", ".webm", ".js", ".css")
                            ):
                                queued.append(canonicalise_url(candidate))
                browser.close()
        except Exception as exc:
            return ProbeResult(
                self.name,
                frozenset(discovered),
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                evidence={"pages_visited": len(visited)},
            )
        return ProbeResult(
            self.name,
            frozenset(discovered),
            evidence={"pages_visited": len(visited), "rendered_pages": len(self.rendered_html)},
        )

    def _in_scope(self, raw_url: str, allowed_hosts: tuple[str, ...]) -> bool:
        try:
            url = canonicalise_url(urljoin(raw_url, raw_url))
        except ValueError:
            return False
        host = (urlsplit(url).hostname or "").lower()
        return host in allowed_hosts and self.url_filter(url)

    def _add(self, raw_url: str, allowed_hosts: tuple[str, ...], discovered: set[str]) -> bool:
        if not self._in_scope(raw_url, allowed_hosts):
            return False
        url = canonicalise_url(raw_url)
        discovered.add(url)
        return True
