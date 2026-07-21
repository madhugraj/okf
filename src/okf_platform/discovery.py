"""Deterministic HTML and sitemap link discovery."""

from __future__ import annotations

from html.parser import HTMLParser
from io import BytesIO
from xml.etree import ElementTree

from .policy import PolicyViolation, canonicalise_url


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.base_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "base" and values.get("href") and self.base_href is None:
            self.base_href = values["href"]
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag in {"iframe", "embed", "img", "script", "source", "video", "audio", "track"} and values.get("src"):
            self.links.append(values["src"])
        if tag == "link" and values.get("href"):
            self.links.append(values["href"])
        if tag == "object" and values.get("data"):
            self.links.append(values["data"])
        if tag in {"img", "source"} and values.get("srcset"):
            self.links.extend(
                candidate.strip().split(" ", 1)[0]
                for candidate in values["srcset"].split(",")
                if candidate.strip()
            )


def discover_html_links(html: bytes, page_url: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    base_url = page_url
    if parser.base_href:
        try:
            base_url = canonicalise_url(parser.base_href, base_url=page_url)
        except PolicyViolation:
            base_url = page_url

    output: list[str] = []
    seen: set[str] = set()
    for raw_link in parser.links:
        try:
            link = canonicalise_url(raw_link, base_url=base_url)
        except (PolicyViolation, ValueError):
            continue
        if link not in seen:
            seen.add(link)
            output.append(link)
    return output


def discover_sitemap_urls(xml: bytes) -> tuple[list[str], list[str]]:
    """Return page/document URLs and nested sitemap URLs from XML sitemap bytes."""

    root = ElementTree.parse(BytesIO(xml)).getroot()
    namespace = root.tag.partition("}")[0].lstrip("{") if "}" in root.tag else ""
    prefix = f"{{{namespace}}}" if namespace else ""
    locations = [
        (node.text or "").strip()
        for node in root.findall(f".//{prefix}loc")
        if (node.text or "").strip()
    ]
    if root.tag.endswith("sitemapindex"):
        return [], locations
    return locations, []
