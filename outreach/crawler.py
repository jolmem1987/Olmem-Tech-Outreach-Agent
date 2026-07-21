from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections import deque
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from outreach.models import SitePage
from outreach.util import is_public_http_url, normalize_url, same_registrable_host


USER_AGENT = "OlmemOutreachResearchBot/1.0 (+https://www.olmemtech.com/contact)"
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
EXCLUDED_PATH_PARTS = {
    "/admin",
    "/account",
    "/login",
    "/logout",
    "/cart",
    "/checkout",
    "/privacy",
    "/terms",
    "/subscribe",
}


class WebCrawler:
    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        )

    def close(self) -> None:
        self.client.close()

    def _robots(self, base_url: str) -> robotparser.RobotFileParser:
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            response = self.client.get(robots_url)
            if response.status_code < 400:
                rp.parse(response.text.splitlines())
            else:
                rp.parse([])
        except httpx.HTTPError:
            rp.parse([])
        return rp

    def _sitemap_urls(self, base_url: str, max_urls: int) -> list[str]:
        parsed = urlparse(base_url)
        roots = [f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"]
        found: list[str] = []
        visited: set[str] = set()
        while roots and len(found) < max_urls:
            sitemap_url = roots.pop(0)
            if sitemap_url in visited:
                continue
            visited.add(sitemap_url)
            try:
                response = self.client.get(sitemap_url, headers={"Accept": "application/xml,text/xml,*/*"})
                if response.status_code >= 400 or len(response.content) > 2_000_000:
                    continue
                root = ET.fromstring(response.content)
            except (httpx.HTTPError, ET.ParseError):
                continue
            for loc in root.findall(".//{*}loc"):
                if not loc.text:
                    continue
                url = loc.text.strip()
                if url.lower().endswith(".xml"):
                    roots.append(url)
                elif same_registrable_host(url, base_url):
                    found.append(url)
                    if len(found) >= max_urls:
                        break
        return found

    def _allowed(self, url: str, base_url: str, rp: robotparser.RobotFileParser) -> bool:
        normalized = normalize_url(url)
        if not normalized or not same_registrable_host(normalized, base_url):
            return False
        path = urlparse(normalized).path.lower()
        if any(part in path for part in EXCLUDED_PATH_PARTS):
            return False
        if not is_public_http_url(normalized):
            return False
        return rp.can_fetch(USER_AGENT, normalized)

    def fetch_page(self, url: str) -> tuple[SitePage | None, list[str], dict[str, str]]:
        try:
            response = self.client.get(url)
            content_type = response.headers.get("content-type", "")
            if response.status_code >= 400 or "text/html" not in content_type:
                return None, [], {}
            if len(response.content) > 2_000_000:
                return None, [], {}
        except httpx.HTTPError:
            return None, [], {}

        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup(["script", "style", "noscript", "svg", "canvas"]):
            element.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        description_tag = soup.find("meta", attrs={"name": re.compile("description", re.I)})
        description = description_tag.get("content", "").strip() if description_tag else ""
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        text = text[:20_000]
        canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
        final_url = normalize_url(canonical.get("href"), str(response.url)) if canonical else str(response.url)
        final_url = final_url or str(response.url)

        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            candidate = normalize_url(anchor["href"], final_url)
            if candidate:
                links.append(candidate)

        emails: dict[str, str] = {}
        for email in EMAIL_RE.findall(response.text):
            emails[email.lower()] = final_url
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if href.lower().startswith("mailto:"):
                email = href[7:].split("?", 1)[0].strip().lower()
                if EMAIL_RE.fullmatch(email):
                    emails[email] = final_url

        page = SitePage(
            url=final_url,
            title=title,
            description=description,
            text=text,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        return page, links, emails

    def crawl(self, base_url: str, max_pages: int) -> tuple[list[SitePage], dict[str, str]]:
        normalized_base = normalize_url(base_url)
        if not normalized_base or not is_public_http_url(normalized_base):
            raise ValueError("Website URL is invalid or not public")

        rp = self._robots(normalized_base)
        seeds = self._sitemap_urls(normalized_base, max_pages * 3)
        queue = deque([normalized_base, *seeds])
        visited: set[str] = set()
        pages: list[SitePage] = []
        emails: dict[str, str] = {}

        while queue and len(pages) < max_pages:
            url = normalize_url(queue.popleft())
            if not url or url in visited:
                continue
            visited.add(url)
            if not self._allowed(url, normalized_base, rp):
                continue
            page, links, page_emails = self.fetch_page(url)
            if page is None or len(page.text) < 80:
                continue
            pages.append(page)
            emails.update(page_emails)
            for link in links:
                if link not in visited and self._allowed(link, normalized_base, rp):
                    queue.append(link)
        return pages, emails
