from __future__ import annotations

from datetime import date
from itertools import zip_longest
from urllib.parse import urlparse

import httpx

from outreach.config import get_settings
from outreach.criteria import get_criteria
from outreach.models import Candidate, OfferCatalog
from outreach.util import (
    is_blocked_platform,
    is_non_business_host,
    looks_like_listicle,
    normalize_domain,
    normalize_url,
)


class ProspectDiscovery:
    def __init__(self) -> None:
        self.settings = get_settings()
        regions_raw = get_criteria()["discovery_regions"]
        self.regions = [item.strip() for item in regions_raw.split(",") if item.strip()]

    def _queries(self, catalog: OfferCatalog) -> list[str]:
        """Build this run's search queries.

        Three things shape the list:

        Offers that sell to a local trade are searched once per region, because
        a roofer is found by where they work. Offers marked region_scoped=false
        are searched as written - an online parts seller has no service area,
        and appending a city returns the local retail counter instead.

        Queries are interleaved round-robin across offers, so the cap trims
        every offer evenly instead of dropping the tail of the catalog.

        The list is then rotated by day, so consecutive runs explore different
        parts of the space. Without this the cap would pin every run to the same
        first N queries and discovery would keep rediscovering the same domains.
        """
        per_offer: list[tuple[int, list[str]]] = []
        for offer in catalog.offers:
            if offer.discovery_weight == 0:  # parked: still sellable, not searched for
                continue
            bases = offer.search_queries or offer.ideal_customer_signals[:3]
            if offer.region_scoped and self.regions:
                queries = [f"{base} {region} business" for base in bases for region in self.regions]
            else:
                queries = list(bases)
            if queries:
                per_offer.append((offer.discovery_weight, queries))
        if not per_offer:
            return []

        cap = max(10, self.settings.max_discoveries_per_run * 2)
        total_weight = sum(weight for weight, _ in per_offer)
        day = date.today().toordinal()

        selected: list[list[str]] = []
        leftovers: list[str] = []
        for weight, queries in per_offer:
            share = max(1, round(cap * weight / total_weight))
            start = (day * share) % len(queries)
            rotated = queries[start:] + queries[:start]
            selected.append(rotated[:share])
            leftovers.extend(rotated[share:])

        chosen = [query for row in zip_longest(*selected) for query in row if query]
        chosen.extend(leftovers)  # top up to the cap if an offer had fewer than its share
        return list(dict.fromkeys(chosen))[:cap]

    def _from_feed(self) -> list[Candidate]:
        if not self.settings.prospect_feed_url:
            return []
        headers = {}
        if self.settings.prospect_feed_token:
            headers["Authorization"] = f"Bearer {self.settings.prospect_feed_token}"
        try:
            response = httpx.get(self.settings.prospect_feed_url, headers=headers, timeout=20)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        candidates: list[Candidate] = []
        for item in payload.get("candidates", payload if isinstance(payload, list) else []):
            try:
                candidates.append(Candidate.model_validate(item))
            except ValueError:
                continue
        return candidates

    def _from_tavily(self, queries: list[str]) -> list[Candidate]:
        if not self.settings.tavily_api_key:
            return []
        candidates: list[Candidate] = []
        for query in queries:
            if len(candidates) >= self.settings.max_discoveries_per_run * 2:
                break
            try:
                response = httpx.post(
                    "https://api.tavily.com/search",
                    timeout=25,
                    # Tavily originally took the key in the body and now expects a
                    # bearer header. Send both so the job does not silently return
                    # nothing if either form is retired.
                    headers={"Authorization": f"Bearer {self.settings.tavily_api_key}"},
                    json={
                        "api_key": self.settings.tavily_api_key,
                        "query": query,
                        "search_depth": "basic",
                        "max_results": 6,
                        "include_answer": False,
                        "include_raw_content": False,
                    },
                )
                response.raise_for_status()
                results = response.json().get("results", [])
            except (httpx.HTTPError, ValueError):
                continue
            for result in results:
                url = normalize_url(result.get("url", ""))
                title = result.get("title")
                if not url or is_blocked_platform(url) or is_non_business_host(url):
                    continue
                if looks_like_listicle(url, title):
                    continue
                candidates.append(
                    Candidate(
                        company_name=result.get("title"),
                        website=url,
                        source_query=query,
                        source_url=url,
                    )
                )
        return candidates

    def discover(self, catalog: OfferCatalog) -> list[Candidate]:
        own_domain = normalize_domain(self.settings.site_base_url)
        raw = [*self._from_feed(), *self._from_tavily(self._queries(catalog))]
        deduped: dict[str, Candidate] = {}
        for candidate in raw:
            url = normalize_url(candidate.website)
            if not url:
                continue
            domain = normalize_domain(url)
            if not domain or domain == own_domain or is_blocked_platform(url):
                continue
            if is_non_business_host(url):
                continue
            parsed = urlparse(url)
            root = f"{parsed.scheme}://{parsed.netloc}/"
            deduped.setdefault(domain, candidate.model_copy(update={"website": root}))
            if len(deduped) >= self.settings.max_discoveries_per_run:
                break
        return list(deduped.values())
