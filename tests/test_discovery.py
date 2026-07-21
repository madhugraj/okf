from okf_platform.discovery import discover_html_links, discover_sitemap_urls


def test_html_discovery_resolves_and_deduplicates_links() -> None:
    html = b"""
    <html><head><base href="/archive/"></head><body>
      <a href="FY24.pdf#page=2">one</a>
      <a href="FY24.pdf">duplicate</a>
      <iframe src="/embedded/report.pdf"></iframe>
      <a href="mailto:info@example.com">email</a>
    </body></html>
    """
    assert discover_html_links(html, "https://example.com/policies") == [
        "https://example.com/archive/FY24.pdf",
        "https://example.com/embedded/report.pdf",
    ]


def test_urlset_sitemap_discovery() -> None:
    xml = b"""<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/a</loc></url>
      <url><loc>https://example.com/b.pdf</loc></url>
    </urlset>"""
    assert discover_sitemap_urls(xml) == (
        ["https://example.com/a", "https://example.com/b.pdf"],
        [],
    )


def test_sitemap_index_discovery() -> None:
    xml = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
    </sitemapindex>"""
    assert discover_sitemap_urls(xml) == ([], ["https://example.com/sitemap-pages.xml"])
