"""Robots.txt snapshot parsing and deterministic access checks."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from .models import FetchResponse
from .policy import CrawlPolicy, canonicalise_url


@dataclass(slots=True)
class RobotsRules:
    """Auditable robots snapshot used for every crawl decision."""

    url: str
    status_code: int
    body: bytes
    user_agent: str
    _parser: RobotFileParser = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._parser = RobotFileParser()
        self._parser.set_url(self.url)
        if self.status_code in {401, 403}:
            self._parser.parse(["User-agent: *", "Disallow: /"])
        elif self.status_code >= 400:
            self._parser.parse([])
        else:
            self._parser.parse(self.body.decode("utf-8", errors="replace").splitlines())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    @property
    def crawl_delay(self) -> float | None:
        delay = self._parser.crawl_delay(self.user_agent)
        if delay is None:
            delay = self._parser.crawl_delay("*")
        return float(delay) if delay is not None else None

    @property
    def sitemap_urls(self) -> tuple[str, ...]:
        urls: list[str] = []
        for line in self.body.decode("utf-8", errors="replace").splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip().lower() == "sitemap" and value.strip():
                urls.append(canonicalise_url(value.strip(), base_url=self.url))
        return tuple(dict.fromkeys(urls))

    def allowed(self, url: str) -> bool:
        return self._parser.can_fetch(self.user_agent, url)

    @classmethod
    def fetch(cls, target_url: str, policy: CrawlPolicy, fetcher) -> RobotsRules:
        robots_url = canonicalise_url(urljoin(target_url, "/robots.txt"))
        response: FetchResponse = fetcher(robots_url)
        return cls(robots_url, response.status_code, response.body, policy.user_agent)
