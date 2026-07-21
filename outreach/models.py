from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class Evidence(BaseModel):
    url: str
    quote_or_fact: str = Field(min_length=3, max_length=500)


class SitePage(BaseModel):
    url: str
    title: str = ""
    description: str = ""
    text: str
    content_hash: str


class Offer(BaseModel):
    offer_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,80}$")
    name: str
    summary: str
    problems_solved: list[str]
    ideal_customer_signals: list[str]
    exclusion_signals: list[str] = []
    allowed_claims: list[str]
    call_to_action: str
    landing_url: str
    evidence_urls: list[str]
    search_queries: list[str] = []


class OfferCatalog(BaseModel):
    catalog_version: str
    generated_from: Literal["manifest", "website_crawl"]
    offers: list[Offer]


class CatalogExtraction(BaseModel):
    offers: list[Offer]


class Candidate(BaseModel):
    company_name: str | None = None
    website: str
    source_query: str
    source_url: str | None = None


class ProspectResearch(BaseModel):
    company_name: str
    website: str
    company_domain: str
    business_email: str | None = None
    business_email_source_url: str | None = None
    contact_name: str | None = None
    contact_role: str | None = None
    public_contact_page: str | None = None
    company_summary: str
    observed_problems: list[str]
    positive_signals: list[str]
    negative_signals: list[str]
    evidence: list[Evidence]


class ScoreComponents(BaseModel):
    problem_evidence: int = Field(ge=0, le=35)
    offer_alignment: int = Field(ge=0, le=30)
    customer_fit: int = Field(ge=0, le=15)
    contact_quality: int = Field(ge=0, le=10)
    timing_signal: int = Field(ge=0, le=10)

    @property
    def total(self) -> int:
        return (
            self.problem_evidence
            + self.offer_alignment
            + self.customer_fit
            + self.contact_quality
            + self.timing_signal
        )


class FitAssessment(BaseModel):
    selected_offer_key: str | None = None
    components: ScoreComponents
    rationale: str
    evidence: list[Evidence]
    contradictions: list[str] = []
    recommended_angle: str | None = None

    @property
    def total_score(self) -> int:
        return self.components.total


class EmailDraft(BaseModel):
    subject: str = Field(min_length=3, max_length=90)
    text_body: str = Field(min_length=40, max_length=1800)
    html_body: str = Field(min_length=40, max_length=5000)
    claims_used: list[str]
    evidence_used: list[Evidence]


class SendDecision(BaseModel):
    eligible: bool
    reasons: list[str]
