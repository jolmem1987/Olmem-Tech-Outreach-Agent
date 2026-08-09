from __future__ import annotations

import html
from types import SimpleNamespace
from typing import Any

from outreach.catalog import CatalogBuilder, load_local_catalog
from outreach.composer import EmailComposer
from outreach.config import get_settings
from outreach.criteria import get_criteria
from outreach.db import init_db, job_lock
from outreach.discovery import ProspectDiscovery
from outreach.models import FitAssessment, OfferCatalog, ProspectResearch
from outreach.repository import (
    count_messages_for,
    count_sent_today,
    create_custom_message,
    create_message,
    delete_prospect as delete_prospect_row,
    get_active_catalog,
    get_eligible_for_send,
    get_prospect,
    get_open_draft,
    get_prospects_for_research,
    is_suppressed,
    list_unresearched_prospects,
    requeue_rejected,
    mark_message_error,
    mark_message_failed,
    mark_message_sent,
    delete_open_draft,
    delete_prospects,
    mark_rejected,
    mark_research_failed,
    save_catalog,
    save_research_and_fit,
    upsert_candidate,
)
from outreach.research import NoPublicContact, ProspectResearcher
from outreach.scoring import FitScorer
from outreach.sender import SendGridSender
from outreach.suppression import make_unsubscribe_token
from outreach.sync import sync_to_admin
from outreach.util import (
    is_blocked_platform,
    is_non_business_host,
    looks_like_listicle,
)


LOCK_IDS = {
    "catalog": 910001,
    "discover": 910002,
    "research": 910003,
    "send": 910004,
}


def _record(mark: Any, prospect_id: str, reason: str) -> None:
    """Record a per-prospect outcome without letting bookkeeping abort the batch.

    These calls run inside an except block, so anything they raise escapes the
    loop and kills the whole job - which is how one prospect's failure took down
    an entire research run.
    """
    try:
        mark(prospect_id, reason)
    except Exception:  # noqa: BLE001 - the original failure is what matters
        pass


class OutreachOrchestrator:
    def __init__(self) -> None:
        self.settings = get_settings()
        init_db()

    def import_catalog(self) -> dict[str, Any]:
        """Activate the catalog committed at catalog/offers.json.

        The crawl-and-extract path costs an LLM call over the whole site and
        needs the site to allow automated clients. This one is free, offline,
        and exact, so it is the normal way to publish a catalog change.
        """
        with job_lock(LOCK_IDS["catalog"]) as locked:
            if not locked:
                return {"ok": True, "skipped": "catalog job already running"}
            return self._activate(load_local_catalog(), event="catalog_imported")

    def refresh_catalog(self) -> dict[str, Any]:
        with job_lock(LOCK_IDS["catalog"]) as locked:
            if not locked:
                return {"ok": True, "skipped": "catalog job already running"}
            builder = CatalogBuilder()
            catalog = builder.build()
            return self._activate(catalog, event="catalog_refreshed", notes=builder.notes)

    def _activate(
        self, catalog: OfferCatalog, *, event: str, notes: list[str] | None = None
    ) -> dict[str, Any]:
        """Make a freshly built or imported catalog the active one."""
        save_catalog(catalog)
        sync_to_admin(
            event,
            {
                "catalog_version": catalog.catalog_version,
                "generated_from": catalog.generated_from,
                "offers": [
                    {"offer_key": offer.offer_key, "name": offer.name, "landing_url": offer.landing_url}
                    for offer in catalog.offers
                ],
            },
        )
        result: dict[str, Any] = {
            "ok": True,
            "catalog_version": catalog.catalog_version,
            "generated_from": catalog.generated_from,
            "offer_count": len(catalog.offers),
        }
        # Only present when something was skipped or fell back, so an ordinary
        # run stays quiet and an unusual one explains itself on the dashboard.
        if notes:
            result["notes"] = notes
        return result

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

    def purge_blocked_prospects(self) -> dict[str, Any]:
        """Delete already-stored prospects the current filters would now reject.

        Discovery filters at insert time, so tightening the rules leaves earlier
        junk sitting in the queue - and research pays a crawl for each one. Only
        prospects still at 'discovered' are touched, so nothing researched or
        scored is ever lost.
        """
        rows = list_unresearched_prospects()
        doomed: list[str] = []
        for row in rows:
            website = row["website"] or ""
            if (
                is_blocked_platform(website)
                or is_non_business_host(website)
                or looks_like_listicle(website, row.get("company_name"))
            ):
                doomed.append(row["id"])
        deleted = delete_prospects(doomed)
        return {"ok": True, "examined": len(rows), "deleted": deleted}

    def requeue_rejected_prospects(self) -> dict[str, Any]:
        """Send every rejected prospect back through research and scoring.

        Rejection is terminal, so a lowered threshold or a corrected catalog
        would otherwise never be applied to anything already judged.
        """
        return {"ok": True, "requeued": requeue_rejected()}

    def _research_one(
        self,
        prospect_id: str,
        website: str,
        catalog: OfferCatalog,
        researcher: ProspectResearcher,
        scorer: FitScorer,
    ) -> dict[str, Any]:
        """Research, score, and store one prospect.

        Shared by the batch job and the admin's per-prospect button so the two
        cannot drift: a prospect researched by hand is stored, gated, and synced
        exactly as the nightly run would have done it.

        Never raises - the batch must not die on one bad prospect, and the admin
        needs the reason rather than a 500.
        """
        try:
            research = researcher.research(website)
            fit = scorer.score(catalog, research)
            decision = scorer.validate(catalog, research, fit)
            save_research_and_fit(
                prospect_id,
                research,
                fit,
                catalog.catalog_version,
                decision.eligible,
                decision.reasons,
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
            return {
                "outcome": "eligible" if decision.eligible else "rejected",
                "fit_score": fit.total_score,
                "selected_offer_key": fit.selected_offer_key,
                "reasons": decision.reasons,
            }
        except NoPublicContact as exc:
            # Permanent, and caught before either LLM call ran.
            _record(mark_rejected, prospect_id, str(exc))
            return {"outcome": "no_contact", "detail": str(exc)}
        except Exception as exc:  # noqa: BLE001 - one prospect must not kill a batch
            _record(mark_research_failed, prospect_id, str(exc))
            return {"outcome": "failed", "detail": str(exc)}

    def research_prospect(self, prospect_id: str) -> dict[str, Any]:
        """Research and score one prospect on demand.

        The batch job takes whatever is at the front of the queue. This is the
        admin picking a specific company to spend a crawl and two LLM calls on,
        which is also the only way to research something the queue would not
        reach for days. One prospect fits inside a serverless timeout with room
        to spare, where a full batch does not.
        """
        prospect = get_prospect(prospect_id)
        if prospect is None:
            return {"ok": False, "error": "Prospect not found."}
        website = prospect.get("website")
        if not website:
            return {"ok": False, "error": "This prospect has no website to research."}

        catalog = get_active_catalog()
        if catalog is None:
            return {"ok": False, "error": "No active offer catalog. Import or rebuild the catalog first."}

        # Share the batch job's lock: researching the same prospect from both
        # paths at once would spend two crawls and four LLM calls to store one
        # result twice.
        with job_lock(LOCK_IDS["research"]) as locked:
            if not locked:
                return {"ok": False, "error": "The research job is already running. Try again once it finishes."}
            result = self._research_one(
                str(prospect["id"]), website, catalog, ProspectResearcher(), FitScorer()
            )

        outcome = result["outcome"]
        if outcome == "eligible":
            return {
                "ok": True,
                "status": "eligible",
                "message": f"Scored {result['fit_score']} and cleared the gate on {result['selected_offer_key']}.",
            }
        if outcome == "rejected":
            reasons = "; ".join(result.get("reasons") or []) or "the gate refused it"
            return {
                "ok": True,
                "status": "rejected",
                "message": f"Scored {result['fit_score']} and was refused: {reasons}",
            }
        if outcome == "no_contact":
            return {"ok": True, "status": "rejected", "message": f"Rejected: {result['detail']}"}
        return {"ok": False, "error": f"Research failed: {result['detail']}"}

    def delete_prospect(self, prospect_id: str) -> dict[str, Any]:
        """Remove a prospect the admin has judged a bad fit.

        Refused once anything has been emailed. `outreach_messages` cascades on
        delete, so removing a contacted prospect would erase the record of what
        was sent to them and when - which is exactly the record you would need if
        a recipient ever asked. Suppression is keyed by email in its own table,
        so a deleted prospect who unsubscribed stays suppressed and cannot be
        contacted again by a later discovery run.
        """
        prospect = get_prospect(prospect_id)
        if prospect is None:
            return {"ok": False, "error": "Prospect not found."}

        message_count = count_messages_for(prospect_id)
        if prospect.get("last_contacted_at") or message_count:
            return {
                "ok": False,
                "error": (
                    f"{prospect.get('company_name') or 'This prospect'} has {message_count} email(s) on record. "
                    "Deleting it would erase that send history, so nothing was deleted."
                ),
            }

        deleted = delete_prospect_row(prospect_id)
        if not deleted:
            return {"ok": False, "error": "Nothing was deleted."}
        return {
            "ok": True,
            "message": f"{prospect.get('company_name') or prospect.get('domain')} was deleted.",
        }

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
            no_contact = 0
            failed = 0
            for row in rows:
                outcome = self._research_one(
                    str(row["id"]), row["website"], catalog, researcher, scorer
                )
                if outcome["outcome"] == "eligible":
                    eligible += 1
                elif outcome["outcome"] == "rejected":
                    rejected += 1
                elif outcome["outcome"] == "no_contact":
                    no_contact += 1
                else:
                    failed += 1
            return {
                "ok": True,
                "processed": len(rows),
                "eligible": eligible,
                "rejected": rejected,
                "no_public_email": no_contact,
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
                        # Store the draft so it is reviewable in the panel. It used
                        # to be pushed to the admin webhook and dropped, which left
                        # preview mode producing nothing you could actually read.
                        if get_open_draft(str(row["id"]), catalog.catalog_version):
                            continue  # already drafted for this catalog version
                        create_message(
                            str(row["id"]),
                            catalog.catalog_version,
                            offer.offer_key,
                            row["contact_email"],
                            draft.subject,
                            draft.text_body,
                            draft.html_body,
                        )
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

    def draft_prospect(self, prospect_id: str, regenerate: bool = False) -> dict[str, Any]:
        """Compose an outreach draft for one prospect and store it unsent.

        Approval needs something to approve. Drafts were previously only created
        by the send job, so a prospect it had not reached had nothing to review
        and "approve and send" would have composed and sent in a single click.
        """
        prospect = get_prospect(prospect_id)
        if prospect is None:
            return {"ok": False, "error": "Prospect not found."}
        if not prospect.get("research_json") or not prospect.get("fit_json"):
            return {"ok": False, "error": "This prospect has not been researched and scored yet."}
        recipient = prospect.get("contact_email")
        if not recipient:
            return {"ok": False, "error": "This prospect has no verified contact email."}

        catalog = get_active_catalog()
        if catalog is None:
            return {"ok": False, "error": "No active offer catalog."}
        offer = {o.offer_key: o for o in catalog.offers}.get(prospect.get("selected_offer_key"))
        if offer is None:
            return {"ok": False, "error": "The prospect's selected offer is not in the active catalog."}
        # A fit from an older catalog names an offer chosen under the old rubric
        # and the old wording. Drafting from it would pitch the superseded offer.
        if prospect.get("scored_catalog_version") != catalog.catalog_version:
            return {
                "ok": False,
                "error": "This prospect was scored against an older catalog. Run 'Research & score' to re-select the offer first.",
            }


        if regenerate:
            delete_open_draft(prospect_id, catalog.catalog_version)
        existing = get_open_draft(prospect_id, catalog.catalog_version)
        if existing:
            return {"ok": True, "message_id": str(existing["id"]), "reused": True}

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
        return {"ok": True, "message_id": message_id, "subject": draft.subject}

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
        # A fit from an older catalog names an offer chosen under the old rubric
        # and the old wording. Drafting from it would pitch the superseded offer.
        if prospect.get("scored_catalog_version") != catalog.catalog_version:
            return {
                "ok": False,
                "error": "This prospect was scored against an older catalog. Run 'Research & score' to re-select the offer first.",
            }


        # Send exactly what was reviewed. Composing again here would email a
        # different message from the one shown on the page, since each compose is
        # a fresh model call.
        existing = get_open_draft(prospect_id, catalog.catalog_version)
        if existing:
            message_id = str(existing["id"])
            draft = SimpleNamespace(
                subject=existing["subject"],
                text_body=existing["text_body"],
                html_body=existing["html_body"],
            )
        else:
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
            return {"ok": False, "error": str(exc)}

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
            return {"ok": False, "error": str(exc)}
