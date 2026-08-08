from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from outreach.config import get_settings
from outreach.crawler import WebCrawler
from outreach.llm import StructuredLLM
from outreach.models import CatalogExtraction, ExtractedOffer, Offer, OfferCatalog, SitePage
from outreach.util import normalize_domain, stable_json_hash


LOCAL_CATALOG_PATH = Path(__file__).resolve().parent.parent / "catalog" / "offers.json"


def url_key(url: str) -> str:
    """A comparison key for two URLs that address the same page.

    The extraction model is asked to return URLs it saw in the page packet, and
    it very nearly does - but it will hand back "https://example.com" where the
    crawl recorded "https://example.com/", or drop a "www.", or change the case.
    Comparing the raw strings threw those offers away one at a time until the
    catalog came back empty, reported as "the site contains no explicit
    commercial offers" - which reads like a fact about the website rather than a
    string mismatch.

    Scheme, "www.", trailing slash, case, and query string are all ignored.
    """
    parsed = urlparse(url.strip() if "://" in url else f"https://{url.strip()}")
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "/").rstrip("/").lower() or "/"
    return f"{host}{path}"


def slugify_offer_key(value: str) -> str:
    """Coerce a model-supplied key into the `^[a-z0-9][a-z0-9_-]{2,80}$` shape."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:80]


def load_local_catalog(path: Path | None = None) -> OfferCatalog:
    """Build the catalog from the committed JSON file.

    No crawl and no model call, so importing is free and deterministic. Use it
    when the live site blocks automated clients, or simply to avoid paying to
    re-extract offers that are already known and can be stated exactly.

    The version hashes the offers themselves, so editing the file yields a new
    catalog version and correctly forces affected prospects to be rescored.
    """
    source = path or LOCAL_CATALOG_PATH
    if not source.exists():
        raise ValueError(f"No local catalog file at {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    offers: list[Offer] = []
    for index, item in enumerate(payload.get("offers", [])):
        try:
            offers.append(Offer.model_validate(item))
        except ValidationError as exc:
            # This file is hand-edited and version controlled, so a bad entry is a
            # mistake to fix rather than something to skip - but the error has to
            # say which entry, or you are diffing JSON against a pydantic dump.
            label = item.get("offer_key") or item.get("name") or f"offers[{index}]"
            raise ValueError(f"Offer {label!r} in {source.name} is invalid: {exc}") from exc
    if not offers:
        raise ValueError("The local catalog file contains no offers")
    version = payload.get("catalog_version") or stable_json_hash(
        [offer.model_dump(mode="json") for offer in offers]
    )
    return OfferCatalog(catalog_version=version, generated_from="manifest", offers=offers)


CATALOG_INSTRUCTIONS = """
You extract an outreach-safe commercial offer catalog from the company's own website.
Include only services or products the company explicitly offers for sale or consultation.
Do not convert blog posts, portfolio projects, free resources, aspirations, capabilities,
or inferred future services into offers unless the site clearly presents them as available.
Every claim must be directly supported by the supplied page text. Do not add pricing,
features, guarantees, industries, or outcomes not present on the site.

For each offer:
- use a stable lowercase offer_key based on the offer name;
- describe the actual problems it solves and customer signals stated or strongly explicit;
- include exclusion signals that indicate the offer is not appropriate;
- allowed_claims must be conservative claims that can safely appear in outreach;
- landing_url and evidence_urls must be URLs present in the supplied pages;
- search_queries should describe businesses likely to show the stated need, not people;
- do not include generic claims such as guaranteed revenue, guaranteed ranking, or savings
  unless the website explicitly guarantees them.
"""


class CatalogBuilder:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.llm = StructuredLLM()
        # Everything the build decided to ignore, and why. Surfaced by the admin
        # job so a silent fallback or a dropped offer is visible on the page
        # rather than only inferable from a catalog that came back smaller than
        # expected.
        self.notes: list[str] = []

    def _load_manifest(self) -> tuple[OfferCatalog | None, str | None]:
        """Load the site-owned JSON catalog, or explain why we are not using it.

        Every failure here used to be swallowed into a bare `None`, so a 404, a
        typo in the URL, a JSON syntax error and "no manifest configured" were
        indistinguishable - and the expensive crawl-and-extract path ran instead
        with nothing said about why.
        """
        url = self.settings.outreach_catalog_url
        if not url:
            return None, None

        try:
            response = httpx.get(
                url,
                timeout=12,
                follow_redirects=True,
                headers={"User-Agent": "OlmemOutreachResearchBot/1.0", "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            return None, f"OUTREACH_CATALOG_URL ({url}) could not be reached ({exc}); crawling the site instead."

        if response.status_code >= 400:
            return None, (
                f"OUTREACH_CATALOG_URL ({url}) returned HTTP {response.status_code}. "
                "If that endpoint does not exist, unset the variable - crawling the site instead."
            )

        # A missing Next.js route returns a 200 or 404 HTML error page, which
        # .json() rejects with a parse error that says nothing useful.
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type.lower():
            return None, (
                f"OUTREACH_CATALOG_URL ({url}) returned {content_type or 'an unknown content type'} "
                "rather than JSON, so the endpoint probably is not implemented. Crawling the site instead."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            return None, f"OUTREACH_CATALOG_URL ({url}) did not return valid JSON ({exc}); crawling the site instead."

        raw_offers = payload.get("offers", []) if isinstance(payload, dict) else payload
        if not isinstance(raw_offers, list) or not raw_offers:
            return None, f"OUTREACH_CATALOG_URL ({url}) returned no offers; crawling the site instead."

        offers: list[Offer] = []
        for index, item in enumerate(raw_offers):
            try:
                offers.append(Offer.model_validate(item))
            except (ValidationError, TypeError) as exc:
                label = item.get("offer_key") or item.get("name") if isinstance(item, dict) else None
                self.notes.append(f"Manifest offer {label or f'offers[{index}]'} was skipped: {exc}")
        if not offers:
            return None, f"OUTREACH_CATALOG_URL ({url}) returned offers but none were valid; crawling the site instead."

        version = payload.get("catalog_version") if isinstance(payload, dict) else None
        version = version or stable_json_hash([offer.model_dump(mode="json") for offer in offers])
        return OfferCatalog(catalog_version=version, generated_from="manifest", offers=offers), None

    @staticmethod
    def _page_packet(pages: list[SitePage]) -> str:
        chunks: list[str] = []
        for page in pages:
            chunks.append(
                f"URL: {page.url}\nTITLE: {page.title}\nDESCRIPTION: {page.description}\n"
                f"VISIBLE TEXT: {page.text[:9000]}"
            )
        return "\n\n--- PAGE ---\n\n".join(chunks)[:160_000]

    def _to_offer(
        self,
        raw: ExtractedOffer,
        page_lookup: dict[str, str],
        site_host: str,
        seen_keys: set[str],
    ) -> Offer | None:
        """Convert one extracted offer, or record why it could not be used.

        Returns None rather than raising: one unusable offer must cost exactly
        that offer. Previously every check here was a `continue` in a loop with
        no record, so a catalog could come back short - or empty - with nothing
        anywhere saying which offer went missing or why.
        """
        label = (raw.name or raw.offer_key or "unnamed offer").strip()

        landing = page_lookup.get(url_key(raw.landing_url))
        if landing is None:
            self.notes.append(f"{label}: landing_url {raw.landing_url!r} is not one of the crawled pages.")
            return None
        if normalize_domain(landing) != site_host:
            self.notes.append(f"{label}: landing_url {landing!r} is not on {site_host}.")
            return None

        # The landing page is itself a crawled page that describes the offer, so
        # it always qualifies as evidence. Seeding the set with it means a model
        # that cited evidence URLs slightly wrong loses those citations, not the
        # entire offer.
        evidence = {landing}
        for url in raw.evidence_urls:
            actual = page_lookup.get(url_key(url))
            if actual:
                evidence.add(actual)
            else:
                self.notes.append(f"{label}: evidence URL {url!r} was not crawled and has been dropped.")

        key = slugify_offer_key(raw.offer_key) or slugify_offer_key(raw.name)
        if len(key) < 3:
            self.notes.append(f"{label}: could not derive a usable offer_key from {raw.offer_key!r}.")
            return None
        if key in seen_keys:
            self.notes.append(f"{label}: duplicate offer_key {key!r} was skipped.")
            return None

        try:
            offer = Offer(
                offer_key=key,
                name=raw.name,
                summary=raw.summary,
                problems_solved=raw.problems_solved,
                ideal_customer_signals=raw.ideal_customer_signals,
                exclusion_signals=raw.exclusion_signals,
                allowed_claims=raw.allowed_claims,
                call_to_action=raw.call_to_action,
                landing_url=landing,
                evidence_urls=sorted(evidence),
                search_queries=list(dict.fromkeys(raw.search_queries))[:8],
                # region_scoped and discovery_weight keep their defaults: a fresh
                # crawl has no basis for deciding either, and both are editable.
            )
        except ValidationError as exc:
            self.notes.append(f"{label}: rejected by validation ({exc}).")
            return None

        seen_keys.add(key)
        return offer

    def build(self) -> OfferCatalog:
        self.notes = []
        manifest, fallback_reason = self._load_manifest()
        if fallback_reason:
            self.notes.append(fallback_reason)
        if manifest:
            return manifest

        crawler = WebCrawler()
        try:
            pages, _ = crawler.crawl(self.settings.site_base_url, self.settings.site_max_pages)
        finally:
            crawler.close()
        if not pages:
            raise RuntimeError(
                f"No pages of {self.settings.site_base_url} could be crawled. Check that robots.txt "
                "allows the research bot and that the site returns server-rendered HTML."
            )

        extraction = self.llm.parse(
            instructions=CATALOG_INSTRUCTIONS,
            input_text=self._page_packet(pages),
            schema=CatalogExtraction,
        )

        page_lookup = {url_key(page.url): page.url for page in pages}
        site_host = normalize_domain(self.settings.site_base_url)
        seen_keys: set[str] = set()
        valid_offers = [
            offer
            for offer in (self._to_offer(raw, page_lookup, site_host, seen_keys) for raw in extraction.offers)
            if offer is not None
        ]
        if not valid_offers:
            raise RuntimeError(
                f"The extraction returned {len(extraction.offers)} offers from {len(pages)} crawled pages, "
                f"but none could be used. {' '.join(self.notes) if self.notes else ''}".strip()
            )

        version = stable_json_hash([offer.model_dump(mode="json") for offer in valid_offers])
        return OfferCatalog(
            catalog_version=version,
            generated_from="website_crawl",
            offers=valid_offers,
        )
