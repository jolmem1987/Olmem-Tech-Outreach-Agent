from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse, urlunparse


# Domains that can never be a prospect. Local search returns a lot of these:
# a chain's store-locator page for a given town looks exactly like a local
# business result, but there is nobody there to sell a website to. Subdomains
# are covered, so "stores.advanceautoparts.com" is caught by the parent entry.
BLOCKED_HOST_SUFFIXES = (
    # Social and general platforms
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "tiktok.com",
    "pinterest.com",
    "nextdoor.com",
    # Business directories and lead-gen marketplaces
    "yelp.com",
    "yellowpages.com",
    "mapquest.com",
    "bbb.org",
    "angi.com",
    "angieslist.com",
    "homeadvisor.com",
    "thumbtack.com",
    "houzz.com",
    "porch.com",
    "buildzoom.com",
    "manta.com",
    "chamberofcommerce.com",
    "alignable.com",
    "indeed.com",
    "glassdoor.com",
    "tripadvisor.com",
    "zoominfo.com",
    "dnb.com",
    "crunchbase.com",
    # National auto parts chains and their store locators
    "autozone.com",
    "oreillyauto.com",
    "advanceautoparts.com",
    "napaonline.com",
    "genuineparts.com",
    "carquest.com",
    "pepboys.com",
    "partsauthority.com",
    # Parts marketplaces and aggregators
    "rockauto.com",
    "carparts.com",
    "partsgeek.com",
    "1aauto.com",
    "carid.com",
    "summitracing.com",
    "jegs.com",
    "ebay.com",
    "amazon.com",
    "walmart.com",
    # Vehicle listings and data providers
    "carfax.com",
    "cars.com",
    "autotrader.com",
    "cargurus.com",
    "carvana.com",
    "edmunds.com",
    "kbb.com",
    "truecar.com",
    # Manufacturer and big-box sites that rank for contractor searches
    "gaf.com",
    "owenscorning.com",
    "certainteed.com",
    "homedepot.com",
    "lowes.com",
    "menards.com",
    # Business-for-sale and commercial property marketplaces
    "bizbuysell.com",
    "bizquest.com",
    "businessesforsale.com",
    "loopnet.com",
    "sunbeltnetwork.com",
    "businessbroker.net",
    # Ranking, review, and "top companies" aggregators
    "clutch.co",
    "builtin.com",
    "industryselect.com",
    "fixr.com",
    "expertise.com",
    "threebestrated.com",
    "trustpilot.com",
    "birdeye.com",
    "g2.com",
    "capterra.com",
    "superpages.com",
    "nicelocal.com",
    "local.com",
    "citysearch.com",
    # Reference, health, and insurance sites that outrank small businesses
    "wikipedia.org",
    "mayoclinic.org",
    "webmd.com",
    "healthline.com",
    "deltadental.com",
    "deltadentalins.com",
    "cigna.com",
    "aetna.com",
    "humana.com",
    "metlife.com",
    "unitedhealthcare.com",
    # Trade press and general news
    "bdcmagazine.com",
    "constructiondive.com",
    "forbes.com",
    "inc.com",
    "entrepreneur.com",
    "businessinsider.com",
    "prnewswire.com",
    "yahoo.com",
)

# Never a prospect, whatever the domain: government, education, military.
NON_BUSINESS_TLDS = (".gov", ".edu", ".mil")

# Search returns pages, not businesses. These titles belong to articles and
# roundups about an industry rather than a company operating in it.
LISTICLE_TITLE_RE = re.compile(
    r"^\s*(top\b|best\b|what are\b|who are\b|how to\b|\d+\s+(best|top)\b)"
    r"|\b(companies|contractors|providers|shops|businesses|dealers)\s+(in|near|for)\b"
    r"|\bfor sale\b|\brankings?\b|\bdirectory\b|\bnear me\b|\bsell your\b",
    re.I,
)

# Same idea, by URL shape.
ARTICLE_PATH_PARTS = (
    "/blog/",
    "/news/",
    "/article",
    "/wiki/",
    "/guide",
    "/directory",
    "/listings",
    "/category/",
    "/best-",
    "/top-",
)


def is_non_business_host(url: str) -> bool:
    host = normalize_domain(url)
    return host.endswith(NON_BUSINESS_TLDS)


def looks_like_listicle(url: str, title: str | None) -> bool:
    """True when a result is an article or roundup rather than a company site."""
    if title and LISTICLE_TITLE_RE.search(title):
        return True
    path = urlparse(url).path.lower()
    return any(part in path for part in ARTICLE_PATH_PARTS)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_json_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_text(encoded)


def normalize_url(url: str, base: str | None = None) -> str | None:
    value = urljoin(base, url) if base else url
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def normalize_domain(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def same_registrable_host(url: str, base_url: str) -> bool:
    return normalize_domain(url) == normalize_domain(base_url)


def is_blocked_platform(url: str) -> bool:
    host = normalize_domain(url)
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in BLOCKED_HOST_SUFFIXES)


def is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False
    try:
        for result in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM):
            ip = ipaddress.ip_address(result[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
    except socket.gaierror:
        return False
    return True
