from __future__ import annotations

import json

from outreach.criteria import WEIGHT_KEYS, get_criteria, score_instructions
from outreach.models import FitAssessment, OfferCatalog, ProspectResearch, SendDecision


class FitScorer:
    def __init__(self) -> None:
        from outreach.config import get_settings
        from outreach.llm import StructuredLLM

        self.settings = get_settings()
        self.criteria = get_criteria()
        self.llm = StructuredLLM()

    def score(self, catalog: OfferCatalog, research: ProspectResearch) -> FitAssessment:
        payload = {
            "active_offer_catalog": catalog.model_dump(mode="json"),
            "prospect_research": research.model_dump(mode="json"),
        }
        fit = self.llm.parse(
            instructions=score_instructions(self.criteria),
            input_text=json.dumps(payload, indent=2),
            schema=FitAssessment,
        )
        # Enforce the configured per-component maxima regardless of what the
        # model returned, so admin-edited weights are the real ceiling.
        weights = self.criteria["weights"]
        for key in WEIGHT_KEYS:
            current = getattr(fit.components, key)
            setattr(fit.components, key, max(0, min(int(weights[key]), int(current))))
        return fit

    def validate(
        self,
        catalog: OfferCatalog,
        research: ProspectResearch,
        fit: FitAssessment,
    ) -> SendDecision:
        # Prefer the criteria loaded at construction; fall back to defaults
        # (without touching the DB) when validate is used in isolation/tests.
        criteria = getattr(self, "criteria", None)
        if criteria:
            min_fit = criteria["min_fit_score"]
            min_pe = criteria["min_problem_evidence"]
            min_oa = criteria["min_offer_alignment"]
            min_cq = criteria["min_contact_quality"]
        else:
            from outreach.criteria import DEFAULT_GATE_MINIMUMS

            min_fit = self.settings.min_fit_score
            min_pe = DEFAULT_GATE_MINIMUMS["min_problem_evidence"]
            min_oa = DEFAULT_GATE_MINIMUMS["min_offer_alignment"]
            min_cq = DEFAULT_GATE_MINIMUMS["min_contact_quality"]

        reasons: list[str] = []
        offer_keys = {offer.offer_key for offer in catalog.offers}
        research_urls = {item.url for item in research.evidence}
        fit_urls = {item.url for item in fit.evidence}

        if fit.selected_offer_key not in offer_keys:
            reasons.append("No active website offer was selected")
        if fit.total_score < min_fit:
            reasons.append(f"Fit score {fit.total_score} is below {min_fit}")
        if fit.components.problem_evidence < min_pe:
            reasons.append("Problem evidence is too weak")
        if fit.components.offer_alignment < min_oa:
            reasons.append("Offer alignment is too weak")
        if fit.components.contact_quality < min_cq:
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
