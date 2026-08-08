"""Conversion of a model-extracted offer into a stored one.

These cover the failure mode that made a site crawl look like "your website has
no offers": every check in the old loop was a bare `continue`, and the URL
comparison was exact string equality, so a trailing slash silently emptied the
catalog.
"""
from __future__ import annotations

import pytest

from outreach.catalog import CatalogBuilder, slugify_offer_key, url_key
from outreach.models import ExtractedOffer


PAGES = {
    url_key("https://www.example.com/"): "https://www.example.com/",
    url_key("https://www.example.com/pricing"): "https://www.example.com/pricing",
    url_key("https://www.example.com/website-starter"): "https://www.example.com/website-starter",
}


def builder() -> CatalogBuilder:
    """A builder without __init__ - it would construct an OpenAI client and demand env vars."""
    instance = object.__new__(CatalogBuilder)
    instance.notes = []
    return instance


def extracted(**overrides) -> ExtractedOffer:
    payload = {
        "offer_key": "contractor-website",
        "name": "Contractor Website",
        "summary": "A flat-rate website for contractors.",
        "problems_solved": ["No quote form"],
        "ideal_customer_signals": ["Licensed trade contractor"],
        "exclusion_signals": [],
        "allowed_claims": ["The package is $1,500 flat rate"],
        "call_to_action": "Offer to send an outline.",
        "landing_url": "https://www.example.com/website-starter",
        "evidence_urls": ["https://www.example.com/pricing"],
        "search_queries": ["roofing contractor"],
    }
    payload.update(overrides)
    return ExtractedOffer.model_validate(payload)


@pytest.mark.parametrize(
    "a,b",
    [
        ("https://www.example.com", "https://www.example.com/"),
        ("https://example.com/pricing", "https://www.example.com/pricing/"),
        ("http://www.example.com/Pricing", "https://example.com/pricing"),
        ("https://www.example.com/pricing?ref=nav", "https://www.example.com/pricing"),
    ],
)
def test_url_key_treats_equivalent_urls_as_equal(a: str, b: str) -> None:
    assert url_key(a) == url_key(b)


def test_url_key_keeps_distinct_pages_distinct() -> None:
    assert url_key("https://example.com/pricing") != url_key("https://example.com/website-starter")


def test_slugify_offer_key_coerces_prose() -> None:
    assert slugify_offer_key("Contractor Website") == "contractor-website"
    assert slugify_offer_key("  Smart Chat Bot!  ") == "smart-chat-bot"
    assert slugify_offer_key("already-fine") == "already-fine"


def test_trailing_slash_mismatch_no_longer_drops_the_offer() -> None:
    """The original bug: exact string equality against the crawled URL set."""
    b = builder()
    offer = b._to_offer(extracted(landing_url="https://www.example.com/website-starter/"), PAGES, "example.com", set())
    assert offer is not None
    # The stored URL is repaired to the one that was actually crawled.
    assert offer.landing_url == "https://www.example.com/website-starter"


def test_prose_offer_key_is_slugified_rather_than_rejected() -> None:
    b = builder()
    offer = b._to_offer(extracted(offer_key="Contractor Website"), PAGES, "example.com", set())
    assert offer is not None
    assert offer.offer_key == "contractor-website"


def test_uncrawled_landing_url_is_skipped_with_a_note() -> None:
    b = builder()
    offer = b._to_offer(extracted(landing_url="https://www.example.com/invented"), PAGES, "example.com", set())
    assert offer is None
    assert any("invented" in note for note in b.notes)


def test_offsite_landing_url_is_skipped() -> None:
    b = builder()
    pages = {**PAGES, url_key("https://other.com/x"): "https://other.com/x"}
    offer = b._to_offer(extracted(landing_url="https://other.com/x"), pages, "example.com", set())
    assert offer is None
    assert any("not on example.com" in note for note in b.notes)


def test_bad_evidence_url_costs_the_citation_not_the_offer() -> None:
    b = builder()
    offer = b._to_offer(extracted(evidence_urls=["https://www.example.com/nope"]), PAGES, "example.com", set())
    assert offer is not None
    # The landing page always qualifies as evidence, so the offer survives.
    assert offer.evidence_urls == ["https://www.example.com/website-starter"]
    assert any("nope" in note for note in b.notes)


def test_landing_page_is_always_included_in_evidence() -> None:
    b = builder()
    offer = b._to_offer(extracted(), PAGES, "example.com", set())
    assert offer is not None
    assert "https://www.example.com/website-starter" in offer.evidence_urls
    assert "https://www.example.com/pricing" in offer.evidence_urls


def test_duplicate_offer_keys_are_skipped() -> None:
    b = builder()
    seen: set[str] = set()
    first = b._to_offer(extracted(), PAGES, "example.com", seen)
    second = b._to_offer(extracted(name="Another"), PAGES, "example.com", seen)
    assert first is not None
    assert second is None
    assert any("duplicate" in note.lower() for note in b.notes)


def test_unusable_offer_key_is_skipped() -> None:
    b = builder()
    offer = b._to_offer(extracted(offer_key="!!", name="??"), PAGES, "example.com", set())
    assert offer is None
    assert any("offer_key" in note for note in b.notes)
