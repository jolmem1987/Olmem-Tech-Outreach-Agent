"""Identify what a website is built with, from its own markup and headers.

This is a fact about the prospect, not a judgement, so it is detected in code
rather than asked of a model: a language model reading page text will guess
"WordPress" for anything with a blog, and the answer decides which offer is even
applicable. A WordPress site can take a plugin. A Wix site cannot, and a builder
subdomain is itself the problem a rebuild solves.

Signatures are matched against the raw HTML of the first page fetched plus its
response headers, both of which the crawler already has.
"""
from __future__ import annotations

import re

# Ordered: the first match wins, so a hosted builder is identified before the
# generic framework underneath it. Each entry is (label, header keys, patterns).
_SIGNATURES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("Wix", ("x-wix-request-id", "x-wix-published-version"), ("wixstatic.com", "wix.com/website-builder", "_wixcssidx")),
    ("Squarespace", (), ("static1.squarespace.com", "squarespace.com/universal", "squarespace-cdn.com", "content=\"squarespace\"")),
    ("Shopify", ("x-shopid", "x-shopify-stage"), ("cdn.shopify.com", "shopify.theme", "myshopify.com")),
    ("Webflow", (), ("assets.website-files.com", "uploads-ssl.webflow.com", "webflow.io", "content=\"webflow\"")),
    ("GoDaddy Website Builder", (), ("img1.wsimg.com", "content=\"godaddy website builder", "godaddysites.com")),
    ("Weebly", (), ("weeblysite.com", "editmysite.com", "content=\"weebly")),
    ("Duda", (), ("irp.cdn-website.com", "content=\"duda", "dudaone")),
    ("Jimdo", (), ("jimdo.com", "jimdofree.com")),
    ("HubSpot CMS", ("x-hs-cache-config",), ("hs-scripts.com", "hubspotusercontent")),
    ("WordPress", (), ("/wp-content/", "/wp-includes/", "api.w.org", "content=\"wordpress")),
    ("Drupal", ("x-generator",), ("/sites/default/files/", "content=\"drupal")),
    ("Joomla", (), ("/media/jui/", "content=\"joomla")),
    ("Next.js", ("x-nextjs-cache",), ("/_next/static/", "__next_data__")),
    ("React SPA", (), ("<div id=\"root\"></div>", "<div id=\"app\"></div>")),
]

# Free subdomains: the business does not own the address it trades under, which
# is an explicit ideal-customer signal on the entry-level website offers.
_BUILDER_HOSTS = (
    "wixsite.com", "squarespace.com", "godaddysites.com", "weebly.com", "weeblysite.com",
    "webflow.io", "myshopify.com", "jimdofree.com", "business.site", "wordpress.com",
    "blogspot.com", "webnode.com", "strikingly.com", "carrd.co",
)


def detect_platform(html: str, headers: dict[str, str] | None = None, url: str = "") -> str | None:
    """Return a platform label, or None when nothing matches confidently."""
    haystack = (html or "").lower()
    header_keys = {key.lower() for key in (headers or {})}

    # A "Drupal" X-Generator is decisive; a bare x-generator is not.
    generator = ""
    if headers:
        generator = str(headers.get("X-Generator") or headers.get("x-generator") or "").lower()

    for label, header_names, patterns in _SIGNATURES:
        if header_names and header_keys.intersection(header_names):
            if label == "Drupal" and "drupal" not in generator:
                pass  # a bare x-generator header belongs to plenty of other stacks
            else:
                return label
        if any(pattern in haystack for pattern in patterns):
            return label
    return None


def is_builder_subdomain(url: str) -> bool:
    """True when the site is served from a website builder's own domain.

    Distinct from the platform: a business can run WordPress on its own domain,
    which is a perfectly good place to install a plugin, or on wordpress.com,
    which is not the same conversation at all.
    """
    from outreach.util import normalize_domain

    host = normalize_domain(url)
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in _BUILDER_HOSTS)


def supports_plugins(platform: str | None) -> bool:
    """Whether third-party plugin code can be installed on this platform."""
    return platform in {"WordPress", "Drupal", "Joomla", "Shopify"}


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def describe(platform: str | None, url: str = "") -> str:
    """A short phrase for the admin UI and the research packet."""
    if platform is None:
        return "unrecognised platform"
    if is_builder_subdomain(url):
        return f"{platform} on a free builder subdomain"
    return platform
