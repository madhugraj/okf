import pytest

from okf_platform.policy import CrawlPolicy, PolicyViolation, canonicalise_url, ensure_in_scope


def test_canonicalise_removes_fragment_default_port_and_sorts_query() -> None:
    assert canonicalise_url("HTTPS://Example.COM:443/a?z=2&a=1#part") == "https://example.com/a?a=1&z=2"


def test_scope_rejects_external_host() -> None:
    policy = CrawlPolicy(("example.com",))
    with pytest.raises(PolicyViolation, match="outside"):
        ensure_in_scope("https://other.example/document.pdf", policy)


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_scope_rejects_non_public_literal_addresses(host: str) -> None:
    policy = CrawlPolicy((host,))
    with pytest.raises(PolicyViolation, match="non-public"):
        ensure_in_scope(f"http://[{host}]/" if ":" in host else f"http://{host}/", policy)


def test_subdomains_require_explicit_permission() -> None:
    with pytest.raises(PolicyViolation):
        ensure_in_scope("https://docs.example.com/a.pdf", CrawlPolicy(("example.com",)))
    assert ensure_in_scope(
        "https://docs.example.com/a.pdf",
        CrawlPolicy(("example.com",), allow_subdomains=True),
    ) == "https://docs.example.com/a.pdf"
