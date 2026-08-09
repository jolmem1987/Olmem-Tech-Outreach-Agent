from __future__ import annotations

from urllib.parse import urlparse

from outreach.config import get_settings
from outreach.criteria import get_criteria
from outreach.crawler import WebCrawler
from outreach.llm import StructuredLLM
from outreach.models import ProspectResearch, SitePage
from outreach.platform import is_builder_subdomain
from outreach.util import normalize_domain


GENERIC_LOCAL_PARTS = {
    "info",
    "contact",
    "hello",
    "sales",
    "office",
    "support",
    "service",
    "admin",
    "team",
    "inquiries",
    "business",
    "marketing",
    "contactus",
    "customerservice",
    "general",
}

RESEARCH_INSTRUCTIONS = """
Research a business only from the supplied pages on its own public website.
Return factual observations, not assumptions. Do not infer or mention protected or
sensitive personal characteristics. Do not use personal social profiles. Do not guess
email addresses, employee names, revenue, company size, budget, intent, or technology.

Every evidence quote_or_fact must be a short exact quote copied from the visible text of
the supplied URL. A problem or positive signal must be tied to that exact quote. Good signals
include explicit manual processes, outdated or missing website functions, disconnected
systems, hard-to-use customer workflows, stated growth, hiring for relevant work, or an
explicit service gap. Merely belonging to an industry is not a problem signal.

Choose a business email only from the supplied PUBLIC EMAILS list. A contact name and role
may be returned only if explicitly stated on a supplied page. Keep negative signals such as
already having a strong matching system, no-solicitation language, being closed, or having
no meaningful match.
"""


class NoPublicContact(RuntimeError):
    """The site publishes no usable business email.

    A permanent disqualification, not a transient failure: the send gate requires
    a verified public address, so no amount of retrying changes the outcome.
    """


class ProspectResearcher:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.allow_named_public_emails = get_criteria()["allow_named_public_emails"]
        self.llm = StructuredLLM()

    def _is_usable_email(self, email: str) -> bool:
        local_part = email.split("@", 1)[0]
        is_generic = local_part in GENERIC_LOCAL_PARTS or any(
            local_part.startswith(f"{prefix}+") for prefix in GENERIC_LOCAL_PARTS
        )
        return is_generic or self.allow_named_public_emails

    @staticmethod
    def _packet(pages: list[SitePage], emails: dict[str, str]) -> str:
        email_text = "\n".join(f"{email} | source: {source}" for email, source in emails.items())
        page_text = "\n\n--- PAGE ---\n\n".join(
            f"URL: {p.url}\nTITLE: {p.title}\nDESCRIPTION: {p.description}\nVISIBLE TEXT: {p.text[:8000]}"
            for p in pages
        )
        return f"PUBLIC EMAILS:\n{email_text or 'NONE'}\n\nWEBSITE PAGES:\n{page_text}"[:140_000]

    def research(self, website: str) -> ProspectResearch:
        crawler = WebCrawler()
        try:
            pages, emails = crawler.crawl(website, self.settings.prospect_max_pages)
            platform = crawler.platform
        finally:
            crawler.close()
        if not pages:
            raise RuntimeError("No public website pages could be researched")

        # Bail before the model runs. Research and scoring are two LLM calls per
        # prospect, and without a usable published address the gate rejects the
        # prospect regardless of what they return. Contractor sites frequently
        # list a phone number and nothing else, so this is a common case.
        if not any(self._is_usable_email(email) for email in emails):
            raise NoPublicContact("No usable business email is published on the website")

        research = self.llm.parse(
            instructions=RESEARCH_INSTRUCTIONS,
            input_text=self._packet(pages, emails),
            schema=ProspectResearch,
        )
        domain = normalize_domain(website)
        research.website = website
        research.company_domain = domain
        # Overwrite whatever the model put here. These are measured, not read.
        research.site_platform = platform
        research.site_on_builder_subdomain = is_builder_subdomain(website)

        allowed_urls = {p.url for p in pages}
        page_text = {p.url: " ".join(p.text.lower().split()) for p in pages}
        verified_evidence = []
        for item in research.evidence:
            quote = " ".join(item.quote_or_fact.lower().split())
            if item.url in allowed_urls and quote and quote in page_text.get(item.url, ""):
                verified_evidence.append(item)
        research.evidence = verified_evidence
        research.public_contact_page = (
            research.public_contact_page if research.public_contact_page in allowed_urls else None
        )

        if research.business_email:
            email = research.business_email.lower().strip()
            source = emails.get(email)
            if source is None or not self._is_usable_email(email):
                research.business_email = None
                research.business_email_source_url = None
            else:
                research.business_email = email
                research.business_email_source_url = source
        else:
            research.business_email_source_url = None

        if research.business_email_source_url not in allowed_urls:
            research.business_email = None
            research.business_email_source_url = None

        if not research.company_name.strip():
            research.company_name = urlparse(website).hostname or domain
        return research
