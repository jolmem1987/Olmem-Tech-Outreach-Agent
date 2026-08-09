"""Platform detection.

The answer decides which offers are deliverable at all, so a wrong label is
worse than no label: a plugin sold to a Wix site is a refund and an apology.
Each case below uses a marker that genuinely appears in that platform's output.
"""
from __future__ import annotations

import pytest

from outreach.platform import detect_platform, is_builder_subdomain, supports_plugins


@pytest.mark.parametrize(
    "html,headers,expected",
    [
        ('<link href="/wp-content/themes/x/style.css">', {}, "WordPress"),
        ('<link rel="https://api.w.org/" href="/wp-json/">', {}, "WordPress"),
        ('<meta name="generator" content="WordPress 6.4">', {}, "WordPress"),
        ('<script src="//static.wixstatic.com/a.js">', {}, "Wix"),
        ("<html></html>", {"X-Wix-Request-Id": "abc"}, "Wix"),
        ('<img src="https://static1.squarespace.com/x.png">', {}, "Squarespace"),
        ('<script src="https://cdn.shopify.com/s/x.js">', {}, "Shopify"),
        ("<html></html>", {"X-ShopId": "12345"}, "Shopify"),
        ('<img src="https://assets.website-files.com/x.svg">', {}, "Webflow"),
        ('<img src="https://img1.wsimg.com/x.png">', {}, "GoDaddy Website Builder"),
        ('<script src="https://irp.cdn-website.com/x.js">', {}, "Duda"),
        ('<script src="/_next/static/chunks/main.js">', {}, "Next.js"),
        ("<html><body><p>plain html</p></body></html>", {}, None),
    ],
)
def test_detects_platform(html: str, headers: dict, expected: str | None) -> None:
    assert detect_platform(html, headers) == expected


def test_hosted_builder_wins_over_the_framework_underneath() -> None:
    """Wix pages ship a React root; the answer that matters is Wix."""
    html = '<script src="//static.wixstatic.com/a.js"></script><div id="root"></div>'
    assert detect_platform(html, {}) == "Wix"


def test_bare_x_generator_header_is_not_taken_as_drupal() -> None:
    """Plenty of stacks send X-Generator. Only Drupal's own value is decisive."""
    assert detect_platform("<html></html>", {"X-Generator": "SomeOtherCMS 1.0"}) is None
    assert detect_platform("<html></html>", {"X-Generator": "Drupal 10"}) == "Drupal"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://joesroofing.wixsite.com/home", True),
        ("https://mystore.myshopify.com", True),
        ("https://someone.godaddysites.com/", True),
        ("https://joesroofing.com", False),
        ("https://www.olmemtech.com", False),
    ],
)
def test_builder_subdomain(url: str, expected: bool) -> None:
    assert is_builder_subdomain(url) is expected


def test_only_plugin_capable_platforms_accept_a_plugin() -> None:
    assert supports_plugins("WordPress")
    assert supports_plugins("Shopify")
    assert not supports_plugins("Wix")
    assert not supports_plugins("Squarespace")
    assert not supports_plugins("Webflow")
    assert not supports_plugins(None)


def test_wordpress_on_an_owned_domain_is_not_a_builder_subdomain() -> None:
    """The two facts are independent: self-hosted WordPress takes a plugin,
    wordpress.com is a different conversation entirely."""
    assert detect_platform('<link href="/wp-content/x.css">', {}) == "WordPress"
    assert is_builder_subdomain("https://joesroofing.com") is False
    assert is_builder_subdomain("https://joesroofing.wordpress.com") is True
