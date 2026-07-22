from __future__ import annotations

from urllib.parse import urlparse

import httpx

from outreach.config import get_settings
from outreach.criteria import get_criteria
from outreach.models import Candidate, OfferCatalog
from outreach.util import is_blocked_platform, normalize_domain, normalize_url


class ProspectDiscovery:
    def __init__(self) -> None:
        self.settings = get_settings()
        regions_raw = get_criteria()["discovery_regions"]
        self.regions = [item.strip() for item in regions_raw.split(",") if item.strip()]

    def _queries(self, catalog: OfferCatalog) -> list[str]:
        queries: list[str] = []
        for offer in catalog.offers:
            bases = offer.search_queries or offer.ideal_customer_signals[:3]
            for base in bases:
                for region in self.regions:
                    queries.append(f"{base} {region} business")
        return list(dict.fromkeys(queries))[: max(10, self.settings.max_discoveries_per_run * 2)]

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
                if not url or is_blocked_platform(url):
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
            parsed = urlparse(url)
            root = f"{parsed.scheme}://{parsed.netloc}/"
            deduped.setdefault(domain, candidate.model_copy(update={"website": root}))
            if len(deduped) >= self.settings.max_discoveries_per_run:
                break
        return list(deduped.values())
