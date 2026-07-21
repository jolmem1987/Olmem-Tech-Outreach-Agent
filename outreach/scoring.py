from __future__ import annotations

import json

from outreach.models import FitAssessment, OfferCatalog, ProspectResearch, SendDecision


SCORE_INSTRUCTIONS = """
Evaluate whether one current company offer is a strong, evidence-based match for this
business. The number is a fit score, not a probability. Select at most one offer.

Use this exact 100-point rubric:
- problem_evidence, 0-35: concrete website evidence of a real problem the offer solves;
- offer_alignment, 0-30: direct alignment between that problem and an explicit offer;
- customer_fit, 0-15: explicit target-customer or operational fit;
- contact_quality, 0-10: a publicly posted appropriate business email and source URL;
- timing_signal, 0-10: current evidence such as growth, hiring, launch, expansion, or a
  recently described problem. Do not invent timing.

A business should normally remain below 80 unless there is concrete problem evidence,
a direct offer match, at least two independent evidence facts, and a valid public business
email. Industry alone is insufficient. Return contradictions for any no-solicitation text,
closed business, existing strong solution that removes the need, unsupported contact,
or mismatch. Do not select an offer that is absent from the provided catalog.
"""


class FitScorer:
    def __init__(self) -> None:
        from outreach.config import get_settings
        from outreach.llm import StructuredLLM

        self.settings = get_settings()
        self.llm = StructuredLLM()

    def score(self, catalog: OfferCatalog, research: ProspectResearch) -> FitAssessment:
        payload = {
            "active_offer_catalog": catalog.model_dump(mode="json"),
            "prospect_research": research.model_dump(mode="json"),
        }
        return self.llm.parse(
            instructions=SCORE_INSTRUCTIONS,
            input_text=json.dumps(payload, indent=2),
            schema=FitAssessment,
        )

    def validate(
        self,
        catalog: OfferCatalog,
        research: ProspectResearch,
        fit: FitAssessment,
    ) -> SendDecision:
        reasons: list[str] = []
        offer_keys = {offer.offer_key for offer in catalog.offers}
        research_urls = {item.url for item in research.evidence}
        fit_urls = {item.url for item in fit.evidence}

        if fit.selected_offer_key not in offer_keys:
            reasons.append("No active website offer was selected")
        if fit.total_score < self.settings.min_fit_score:
            reasons.append(f"Fit score {fit.total_score} is below {self.settings.min_fit_score}")
        if fit.components.problem_evidence < 20:
            reasons.append("Problem evidence is too weak")
        if fit.components.offer_alignment < 20:
            reasons.append("Offer alignment is too weak")
        if fit.components.contact_quality < 8:
            reasons.append("Contact quality is too weak")
        if not research.business_email or not research.business_email_source_url:
            reasons.append("No verified public business email")
        if len(fit_urls) < 2:
            reasons.append("Fewer than two evidence URLs support the match")
        if not fit_urls.issubset(research_urls):
            reasons.append("The fit includes evidence not present in the website research")
        if not research.observed_problems:
            reasons.append("No concrete problem was observed")
        if fit.contradictions:
            reasons.append("Contradictions or exclusion signals were found")

        return SendDecision(eligible=not reasons, reasons=reasons)
