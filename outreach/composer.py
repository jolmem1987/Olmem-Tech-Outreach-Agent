from __future__ import annotations

import html
import json

from outreach.llm import StructuredLLM
from outreach.models import EmailDraft, FitAssessment, Offer, ProspectResearch


COMPOSER_INSTRUCTIONS = """
Write a concise, truthful B2B outreach email based only on the supplied offer, research,
and fit evidence. The email must be 70-140 words before the compliance footer.

Rules:
- Mention one specific business observation naturally, without saying "I researched you".
- Pitch only the selected website offer and only claims listed in allowed_claims.
- Do not claim guaranteed results, savings, ranking, revenue, or capabilities not supplied.
- Do not be creepy, overfamiliar, urgent, manipulative, or deceptive.
- Use one low-pressure call to action.
- Use the person's name only if an explicit public name and role were supplied.
- Subject must accurately describe the message and must not imitate a reply.
- Do not add a signature, postal address, unsubscribe language, tracking language, or URLs;
  the application adds those consistently.
- html_body should contain the same content as text_body, using only simple paragraphs.
"""


class EmailComposer:
    def __init__(self) -> None:
        self.llm = StructuredLLM()

    def compose(
        self,
        offer: Offer,
        research: ProspectResearch,
        fit: FitAssessment,
    ) -> EmailDraft:
        payload = {
            "selected_offer": offer.model_dump(mode="json"),
            "prospect_research": research.model_dump(mode="json"),
            "fit_assessment": fit.model_dump(mode="json"),
        }
        draft = self.llm.parse(
            instructions=COMPOSER_INSTRUCTIONS,
            input_text=json.dumps(payload, indent=2),
            schema=EmailDraft,
        )

        allowed_claims = set(offer.allowed_claims)
        if not set(draft.claims_used).issubset(allowed_claims):
            raise RuntimeError("Draft attempted to use a claim outside the live site catalog")
        research_urls = {item.url for item in research.evidence}
        if not {item.url for item in draft.evidence_used}.issubset(research_urls):
            raise RuntimeError("Draft attempted to use unsupported prospect evidence")

        draft.text_body = (
            draft.text_body.strip()
            + f"\n\n{offer.call_to_action}: {offer.landing_url}"
        )
        escaped = html.escape(draft.text_body.strip()).replace("\n\n", "</p><p>").replace("\n", "<br>")
        safe_url = html.escape(offer.landing_url, quote=True)
        safe_cta = html.escape(offer.call_to_action)
        # Replace the final plain URL line with one controlled link to the current site offer.
        final_line = html.escape(f"{offer.call_to_action}: {offer.landing_url}")
        escaped = escaped.replace(final_line, f'<a href="{safe_url}">{safe_cta}</a>')
        draft.html_body = f"<p>{escaped}</p>"
        return draft
