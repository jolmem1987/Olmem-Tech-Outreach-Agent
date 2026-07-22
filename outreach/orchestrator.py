from __future__ import annotations

import html
from typing import Any

from outreach.catalog import CatalogBuilder
from outreach.composer import EmailComposer
from outreach.config import get_settings
from outreach.criteria import get_criteria
from outreach.db import init_db, job_lock
from outreach.discovery import ProspectDiscovery
from outreach.models import FitAssessment, OfferCatalog, ProspectResearch
from outreach.repository import (
    count_sent_today,
    create_custom_message,
    create_message,
    get_active_catalog,
    get_eligible_for_send,
    get_prospect,
    get_prospects_for_research,
    is_suppressed,
    mark_message_error,
    mark_message_failed,
    mark_message_sent,
    mark_research_failed,
    save_catalog,
    save_research_and_fit,
    upsert_candidate,
)
from outreach.research import ProspectResearcher
from outreach.scoring import FitScorer
from outreach.sender import SendGridSender
from outreach.suppression import make_unsubscribe_token
from outreach.sync import sync_to_admin


LOCK_IDS = {
    "catalog": 910001,
    "discover": 910002,
    "research": 910003,
    "send": 910004,
}


class OutreachOrchestrator:
    def __init__(self) -> None:
        self.settings = get_settings()
        init_db()

    def refresh_catalog(self) -> dict[str, Any]:
        with job_lock(LOCK_IDS["catalog"]) as locked:
            if not locked:
                return {"ok": True, "skipped": "catalog job already running"}
            catalog = CatalogBuilder().build()
            save_catalog(catalog)
            sync_to_admin(
                "catalog_refreshed",
                {
                    "catalog_version": catalog.catalog_version,
                    "generated_from": catalog.generated_from,
                    "offers": [
                        {"offer_key": offer.offer_key, "name": offer.name, "landing_url": offer.landing_url}
                        for offer in catalog.offers
                    ],
                },
            )
            return {
                "ok": True,
                "catalog_version": catalog.catalog_version,
                "generated_from": catalog.generated_from,
                "offer_count": len(catalog.offers),
            }

    def discover_prospects(self) -> dict[str, Any]:
        with job_lock(LOCK_IDS["discover"]) as locked:
            if not locked:
                return {"ok": True, "skipped": "discovery job already running"}
            catalog = get_active_catalog()
            if catalog is None:
                catalog = CatalogBuilder().build()
                save_catalog(catalog)
            candidates = ProspectDiscovery().discover(catalog)
            inserted = sum(1 for candidate in candidates if upsert_candidate(candidate))
            return {"ok": True, "found": len(candidates), "inserted": inserted}

    def research_and_score(self) -> dict[str, Any]:
        with job_lock(LOCK_IDS["research"]) as locked:
            if not locked:
                return {"ok": True, "skipped": "research job already running"}
            catalog = get_active_catalog()
            if catalog is None:
                return {"ok": False, "error": "No active offer catalog"}
            researcher = ProspectResearcher()
            scorer = FitScorer()
            rows = get_prospects_for_research(self.settings.max_research_per_run)
            eligible = 0
            rejected = 0
            failed = 0
            for row in rows:
                prospect_id = str(row["id"])
                try:
                    research = researcher.research(row["website"])
                    fit = scorer.score(catalog, research)
                    decision = scorer.validate(catalog, research, fit)
                    save_research_and_fit(
                        prospect_id,
                        research,
                        fit,
                        catalog.catalog_version,
                        decision.eligible,
                    )
                    sync_to_admin(
                        "lead_scored",
                        {
                            "prospect_id": prospect_id,
                            "company_name": research.company_name,
                            "website": research.website,
                            "email": research.business_email,
                            "email_source_url": research.business_email_source_url,
                            "fit_score": fit.total_score,
                            "selected_offer_key": fit.selected_offer_key,
                            "eligible": decision.eligible,
                            "reasons": decision.reasons,
                            "research": research.model_dump(mode="json"),
                            "fit": fit.model_dump(mode="json"),
                            "catalog_version": catalog.catalog_version,
                        },
                    )
                    if decision.eligible:
                        eligible += 1
                    else:
                        rejected += 1
                except Exception as exc:
                    mark_research_failed(prospect_id, str(exc))
                    failed += 1
            return {
                "ok": True,
                "processed": len(rows),
                "eligible": eligible,
                "rejected": rejected,
                "failed": failed,
            }

    def send_eligible(self) -> dict[str, Any]:
        with job_lock(LOCK_IDS["send"]) as locked:
            if not locked:
                return {"ok": True, "skipped": "send job already running"}
            catalog = get_active_catalog()
            if catalog is None:
                return {"ok": False, "error": "No active offer catalog"}
            criteria = get_criteria()
            autonomous_send = criteria["autonomous_send"]
            daily_limit = criteria["daily_send_limit"]
            sent_today = count_sent_today()
            remaining = max(0, daily_limit - sent_today)
            if remaining == 0:
                return {"ok": True, "sent": 0, "skipped": "daily limit reached"}

            rows = get_eligible_for_send(remaining, criteria["contact_cooldown_days"])
            offers = {offer.offer_key: offer for offer in catalog.offers}
            composer = EmailComposer()
            sender = SendGridSender()
            sent = 0
            previewed = 0
            failed = 0

            for row in rows:
                offer = offers.get(row["selected_offer_key"])
                if offer is None or row["scored_catalog_version"] != catalog.catalog_version:
                    continue
                research = ProspectResearch.model_validate(row["research_json"])
                fit = FitAssessment.model_validate(row["fit_json"])
                try:
                    draft = composer.compose(offer, research, fit)
                    token = make_unsubscribe_token(row["contact_email"])
                    unsubscribe_url = f"{self.settings.app_base_url}/api/unsubscribe/{token}"

                    if not autonomous_send:
                        sync_to_admin(
                            "outreach_preview",
                            {
                                "prospect_id": str(row["id"]),
                                "company_name": row["company_name"],
                                "recipient_email": row["contact_email"],
                                "fit_score": row["fit_score"],
                                "offer_key": offer.offer_key,
                                "subject": draft.subject,
                                "text_body": draft.text_body,
                            },
                        )
                        previewed += 1
                        continue

                    message_id = create_message(
                        str(row["id"]),
                        catalog.catalog_version,
                        offer.offer_key,
                        row["contact_email"],
                        draft.subject,
                        draft.text_body,
                        draft.html_body,
                    )
                    try:
                        provider_id = sender.send(
                            message_id=message_id,
                            recipient_email=row["contact_email"],
                            subject=draft.subject,
                            text_body=draft.text_body,
                            html_body=draft.html_body,
                            unsubscribe_url=unsubscribe_url,
                        )
                        mark_message_sent(message_id, provider_id)
                        sync_to_admin(
                            "outreach_sent",
                            {
                                "prospect_id": str(row["id"]),
                                "message_id": message_id,
                                "company_name": row["company_name"],
                                "recipient_email": row["contact_email"],
                                "fit_score": row["fit_score"],
                                "offer_key": offer.offer_key,
                                "subject": draft.subject,
                                "reply_to": self.settings.reply_to_email,
                            },
                        )
                        sent += 1
                    except Exception as exc:
                        mark_message_failed(message_id, str(exc))
                        failed += 1
                except Exception:
                    failed += 1

            return {
                "ok": True,
                "autonomous_send": autonomous_send,
                "candidates": len(rows),
                "sent": sent,
                "previewed": previewed,
                "failed": failed,
                "daily_limit": daily_limit,
            }

    # -- Manual, admin-triggered sends ------------------------------------

    def _unsubscribe_url(self, email: str) -> str:
        token = make_unsubscribe_token(email)
        return f"{self.settings.app_base_url}/api/unsubscribe/{token}"

    def send_prospect_now(self, prospect_id: str) -> dict[str, Any]:
        """Compose the AI outreach draft for one prospect and send it now,
        bypassing the autonomous-send gate and daily limit. Still respects the
        suppression list. Used by the admin 'approve & send' action."""
        prospect = get_prospect(prospect_id)
        if prospect is None:
            return {"ok": False, "error": "Prospect not found."}
        recipient = prospect.get("contact_email")
        if not recipient:
            return {"ok": False, "error": "This prospect has no verified contact email."}
        if is_suppressed(recipient):
            return {"ok": False, "error": f"{recipient} is on the suppression (do-not-contact) list."}
        if not prospect.get("research_json") or not prospect.get("fit_json"):
            return {"ok": False, "error": "This prospect has not been researched and scored yet."}

        catalog = get_active_catalog()
        if catalog is None:
            return {"ok": False, "error": "No active offer catalog."}
        offers = {offer.offer_key: offer for offer in catalog.offers}
        offer = offers.get(prospect.get("selected_offer_key"))
        if offer is None:
            return {"ok": False, "error": "The prospect's selected offer is not in the active catalog. Re-run research to rescore."}

        research = ProspectResearch.model_validate(prospect["research_json"])
        fit = FitAssessment.model_validate(prospect["fit_json"])
        try:
            draft = EmailComposer().compose(offer, research, fit)
        except Exception as exc:
            return {"ok": False, "error": f"Draft could not be composed: {exc}"}

        message_id = create_message(
            prospect_id,
            catalog.catalog_version,
            offer.offer_key,
            recipient,
            draft.subject,
            draft.text_body,
            draft.html_body,
        )
        try:
            provider_id = SendGridSender().send(
                message_id=message_id,
                recipient_email=recipient,
                subject=draft.subject,
                text_body=draft.text_body,
                html_body=draft.html_body,
                unsubscribe_url=self._unsubscribe_url(recipient),
            )
            mark_message_sent(message_id, provider_id)
            sync_to_admin(
                "outreach_sent",
                {
                    "prospect_id": prospect_id,
                    "message_id": message_id,
                    "company_name": prospect.get("company_name"),
                    "recipient_email": recipient,
                    "fit_score": prospect.get("fit_score"),
                    "offer_key": offer.offer_key,
                    "subject": draft.subject,
                    "reply_to": self.settings.reply_to_email,
                    "manual": True,
                },
            )
            return {"ok": True, "message_id": message_id, "recipient": recipient, "subject": draft.subject}
        except Exception as exc:
            mark_message_failed(message_id, str(exc))
            return {"ok": False, "error": f"SendGrid rejected the message: {exc}"}

    def send_custom(self, prospect_id: str, subject: str, body: str, recipient: str | None = None) -> dict[str, Any]:
        """Send an admin-written custom email to a prospect."""
        prospect = get_prospect(prospect_id)
        if prospect is None:
            return {"ok": False, "error": "Prospect not found."}
        recipient = (recipient or prospect.get("contact_email") or "").strip()
        if not recipient:
            return {"ok": False, "error": "No recipient email available for this prospect."}
        if is_suppressed(recipient):
            return {"ok": False, "error": f"{recipient} is on the suppression (do-not-contact) list."}
        subject = subject.strip()
        body = body.strip()
        if not subject or not body:
            return {"ok": False, "error": "Subject and message are both required."}

        safe = html.escape(body).replace("\n\n", "</p><p>").replace("\n", "<br>")
        html_body = f"<p>{safe}</p>"
        catalog = get_active_catalog()
        catalog_version = catalog.catalog_version if catalog else "manual"
        message_id = create_custom_message(prospect_id, recipient, subject, body, html_body, catalog_version)
        try:
            provider_id = SendGridSender().send(
                message_id=message_id,
                recipient_email=recipient,
                subject=subject,
                text_body=body,
                html_body=html_body,
                unsubscribe_url=self._unsubscribe_url(recipient),
            )
            mark_message_sent(message_id, provider_id)
            return {"ok": True, "message_id": message_id, "recipient": recipient, "subject": subject}
        except Exception as exc:
            mark_message_error(message_id, str(exc))
            return {"ok": False, "error": f"SendGrid rejected the message: {exc}"}
