from __future__ import annotations

from typing import Any

from outreach.catalog import CatalogBuilder
from outreach.composer import EmailComposer
from outreach.config import get_settings
from outreach.db import init_db, job_lock
from outreach.discovery import ProspectDiscovery
from outreach.models import FitAssessment, OfferCatalog, ProspectResearch
from outreach.repository import (
    count_sent_today,
    create_message,
    get_active_catalog,
    get_eligible_for_send,
    get_prospects_for_research,
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
            sent_today = count_sent_today()
            remaining = max(0, self.settings.daily_send_limit - sent_today)
            if remaining == 0:
                return {"ok": True, "sent": 0, "skipped": "daily limit reached"}

            rows = get_eligible_for_send(remaining, self.settings.contact_cooldown_days)
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

                    if not self.settings.autonomous_send:
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
                "autonomous_send": self.settings.autonomous_send,
                "candidates": len(rows),
                "sent": sent,
                "previewed": previewed,
                "failed": failed,
                "daily_limit": self.settings.daily_send_limit,
            }
