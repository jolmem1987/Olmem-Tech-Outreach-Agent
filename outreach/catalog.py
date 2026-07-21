from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx

from outreach.config import get_settings
from outreach.crawler import WebCrawler
from outreach.llm import StructuredLLM
from outreach.models import CatalogExtraction, Offer, OfferCatalog, SitePage
from outreach.util import stable_json_hash


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

    def _load_manifest(self) -> OfferCatalog | None:
        if not self.settings.outreach_catalog_url:
            return None
        try:
            response = httpx.get(
                self.settings.outreach_catalog_url,
                timeout=12,
                follow_redirects=True,
                headers={"User-Agent": "OlmemOutreachResearchBot/1.0"},
            )
            if response.status_code >= 400:
                return None
            payload = response.json()
            offers = [Offer.model_validate(item) for item in payload.get("offers", [])]
            if not offers:
                return None
            version = payload.get("catalog_version") or stable_json_hash(
                [offer.model_dump(mode="json") for offer in offers]
            )
            return OfferCatalog(catalog_version=version, generated_from="manifest", offers=offers)
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    @staticmethod
    def _page_packet(pages: list[SitePage]) -> str:
        chunks: list[str] = []
        for page in pages:
            chunks.append(
                f"URL: {page.url}\nTITLE: {page.title}\nDESCRIPTION: {page.description}\n"
                f"VISIBLE TEXT: {page.text[:9000]}"
            )
        return "\n\n--- PAGE ---\n\n".join(chunks)[:160_000]

    def build(self) -> OfferCatalog:
        manifest = self._load_manifest()
        if manifest:
            return manifest

        crawler = WebCrawler()
        try:
            pages, _ = crawler.crawl(self.settings.site_base_url, self.settings.site_max_pages)
        finally:
            crawler.close()
        if not pages:
            raise RuntimeError("No website pages were available to build the offer catalog")

        extraction = self.llm.parse(
            instructions=CATALOG_INSTRUCTIONS,
            input_text=self._page_packet(pages),
            schema=CatalogExtraction,
        )
        page_urls = {page.url for page in pages}
        site_host = urlparse(self.settings.site_base_url).hostname
        valid_offers: list[Offer] = []
        for offer in extraction.offers:
            evidence = [url for url in offer.evidence_urls if url in page_urls]
            if offer.landing_url not in page_urls or not evidence:
                continue
            if urlparse(offer.landing_url).hostname != site_host:
                continue
            offer.evidence_urls = sorted(set(evidence))
            offer.search_queries = list(dict.fromkeys(offer.search_queries))[:8]
            valid_offers.append(offer)
        if not valid_offers:
            raise RuntimeError("The site crawl did not contain any explicit commercial offers")

        version = stable_json_hash([offer.model_dump(mode="json") for offer in valid_offers])
        return OfferCatalog(
            catalog_version=version,
            generated_from="website_crawl",
            offers=valid_offers,
        )
