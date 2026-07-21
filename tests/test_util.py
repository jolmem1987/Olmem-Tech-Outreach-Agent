from outreach.util import normalize_domain, normalize_url


def test_normalize_domain() -> None:
    assert normalize_domain("https://www.Example.com/path") == "example.com"


def test_normalize_url_removes_fragment() -> None:
    assert normalize_url("/about#team", "https://example.com") == "https://example.com/about"
