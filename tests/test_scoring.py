from types import SimpleNamespace

from outreach.models import (
    Evidence,
    FitAssessment,
    Offer,
    OfferCatalog,
    ProspectResearch,
    ScoreComponents,
)
from outreach.scoring import FitScorer


def sample_catalog() -> OfferCatalog:
    return OfferCatalog(
        catalog_version="v1",
        generated_from="manifest",
        offers=[
            Offer(
                offer_key="workflow-automation",
                name="Workflow Automation",
                summary="Automates a stated business workflow.",
                problems_solved=["manual lead routing"],
                ideal_customer_signals=["manual intake"],
                exclusion_signals=["already automated"],
                allowed_claims=["Custom workflow automation"],
                call_to_action="Discuss the workflow",
                landing_url="https://www.olmemtech.com/workflow-automation",
                evidence_urls=["https://www.olmemtech.com/workflow-automation"],
            )
        ],
    )


def sample_research() -> ProspectResearch:
    return ProspectResearch(
        company_name="Example Co",
        website="https://example.com/",
        company_domain="example.com",
        business_email="info@example.com",
        business_email_source_url="https://example.com/contact",
        company_summary="Example business",
        observed_problems=["All requests are routed manually by phone."],
        positive_signals=["The company is hiring an office coordinator."],
        negative_signals=[],
        evidence=[
            Evidence(url="https://example.com/contact", quote_or_fact="Public info email"),
            Evidence(url="https://example.com/services", quote_or_fact="Requests are handled by phone"),
        ],
    )


def test_valid_80_plus_fit_passes() -> None:
    scorer = FitScorer.__new__(FitScorer)
    scorer.settings = SimpleNamespace(min_fit_score=80)
    fit = FitAssessment(
        selected_offer_key="workflow-automation",
        components=ScoreComponents(
            problem_evidence=30,
            offer_alignment=25,
            customer_fit=12,
            contact_quality=8,
            timing_signal=6,
        ),
        rationale="Concrete manual workflow aligns to the offer.",
        evidence=sample_research().evidence,
        contradictions=[],
        recommended_angle="Manual intake routing",
    )
    decision = scorer.validate(sample_catalog(), sample_research(), fit)
    assert fit.total_score == 81
    assert decision.eligible is True


def test_industry_only_or_missing_evidence_is_blocked() -> None:
    scorer = FitScorer.__new__(FitScorer)
    scorer.settings = SimpleNamespace(min_fit_score=80)
    research = sample_research()
    research.observed_problems = []
    fit = FitAssessment(
        selected_offer_key="workflow-automation",
        components=ScoreComponents(
            problem_evidence=10,
            offer_alignment=25,
            customer_fit=15,
            contact_quality=10,
            timing_signal=10,
        ),
        rationale="Same industry only.",
        evidence=[research.evidence[0]],
        contradictions=[],
    )
    decision = scorer.validate(sample_catalog(), research, fit)
    assert decision.eligible is False
    assert "Problem evidence is too weak" in decision.reasons
    assert "Fewer than two evidence URLs support the match" in decision.reasons
