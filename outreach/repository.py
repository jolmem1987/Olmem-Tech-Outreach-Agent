from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from outreach.db import connection, json_dumps
from outreach.models import Candidate, FitAssessment, OfferCatalog, ProspectResearch


def save_catalog(catalog: OfferCatalog) -> None:
    with connection() as conn:
        conn.execute("UPDATE outreach_catalog_versions SET active = FALSE WHERE active = TRUE")
        conn.execute(
            """
            INSERT INTO outreach_catalog_versions
                (catalog_version, generated_from, catalog_json, active)
            VALUES (%s, %s, %s::jsonb, TRUE)
            ON CONFLICT (catalog_version) DO UPDATE SET
                generated_from = EXCLUDED.generated_from,
                catalog_json = EXCLUDED.catalog_json,
                active = TRUE
            """,
            (catalog.catalog_version, catalog.generated_from, json_dumps(catalog.model_dump())),
        )
        conn.execute("UPDATE outreach_offers SET active = FALSE")
        for offer in catalog.offers:
            conn.execute(
                """
                INSERT INTO outreach_offers
                    (offer_key, catalog_version, offer_json, active, updated_at)
                VALUES (%s, %s, %s::jsonb, TRUE, NOW())
                ON CONFLICT (offer_key) DO UPDATE SET
                    catalog_version = EXCLUDED.catalog_version,
                    offer_json = EXCLUDED.offer_json,
                    active = TRUE,
                    updated_at = NOW()
                """,
                (offer.offer_key, catalog.catalog_version, json_dumps(offer.model_dump())),
            )
        conn.execute(
            """
            UPDATE outreach_prospects
            SET status = 'needs_rescore', updated_at = NOW()
            WHERE status IN ('eligible', 'rejected', 'researched')
              AND scored_catalog_version IS DISTINCT FROM %s
            """,
            (catalog.catalog_version,),
        )
        conn.commit()


def get_active_catalog() -> OfferCatalog | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT catalog_json
            FROM outreach_catalog_versions
            WHERE active = TRUE
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    return OfferCatalog.model_validate(row["catalog_json"]) if row else None


def upsert_candidate(candidate: Candidate) -> bool:
    from outreach.util import normalize_domain

    domain = normalize_domain(candidate.website)
    if not domain:
        return False
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO outreach_prospects
                (company_name, website, domain, source_query, source_url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (domain) DO NOTHING
            RETURNING id
            """,
            (
                candidate.company_name,
                candidate.website,
                domain,
                candidate.source_query,
                candidate.source_url,
            ),
        ).fetchone()
        conn.commit()
    return row is not None


def get_prospects_for_research(limit: int) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM outreach_prospects
            WHERE status IN ('discovered', 'needs_rescore', 'research_failed')
            ORDER BY updated_at ASC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return list(rows)


def save_research_and_fit(
    prospect_id: str,
    research: ProspectResearch,
    fit: FitAssessment,
    catalog_version: str,
    eligible: bool,
) -> None:
    status = "eligible" if eligible else "rejected"
    with connection() as conn:
        conn.execute(
            """
            UPDATE outreach_prospects
            SET company_name = %s,
                website = %s,
                domain = %s,
                status = %s,
                research_json = %s::jsonb,
                contact_email = %s,
                contact_email_source_url = %s,
                selected_offer_key = %s,
                fit_score = %s,
                fit_json = %s::jsonb,
                scored_catalog_version = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                research.company_name,
                research.website,
                research.company_domain,
                status,
                json_dumps(research.model_dump()),
                research.business_email,
                research.business_email_source_url,
                fit.selected_offer_key,
                fit.total_score,
                json_dumps(fit.model_dump()),
                catalog_version,
                prospect_id,
            ),
        )
        conn.commit()


def mark_research_failed(prospect_id: str, reason: str) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE outreach_prospects
            SET status = 'research_failed',
                fit_json = jsonb_build_object('error', %s),
                updated_at = NOW()
            WHERE id = %s
            """,
            (reason[:1000], prospect_id),
        )
        conn.commit()


def get_eligible_for_send(limit: int, cooldown_days: int) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT p.*
            FROM outreach_prospects p
            JOIN outreach_catalog_versions c
              ON c.catalog_version = p.scored_catalog_version AND c.active = TRUE
            LEFT JOIN outreach_suppressions s
              ON LOWER(s.email) = LOWER(p.contact_email)
            WHERE p.status = 'eligible'
              AND p.contact_email IS NOT NULL
              AND s.email IS NULL
              AND (
                    p.last_contacted_at IS NULL
                    OR p.last_contacted_at < NOW() - make_interval(days => %s)
                  )
              AND NOT EXISTS (
                    SELECT 1 FROM outreach_messages m
                    WHERE m.prospect_id = p.id AND m.status IN ('sent', 'delivered')
                  )
            ORDER BY p.fit_score DESC, p.updated_at ASC
            LIMIT %s
            """,
            (cooldown_days, limit),
        ).fetchall()
    return list(rows)


def create_message(
    prospect_id: str,
    catalog_version: str,
    offer_key: str,
    recipient_email: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> str:
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO outreach_messages
                (prospect_id, catalog_version, offer_key, recipient_email,
                 subject, text_body, html_body)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                prospect_id,
                catalog_version,
                offer_key,
                recipient_email,
                subject,
                text_body,
                html_body,
            ),
        ).fetchone()
        conn.execute(
            "UPDATE outreach_prospects SET status = 'sending', updated_at = NOW() WHERE id = %s",
            (prospect_id,),
        )
        conn.commit()
    return str(row["id"])


def mark_message_sent(message_id: str, provider_message_id: str | None) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE outreach_messages
            SET status = 'sent', provider_message_id = %s, sent_at = NOW()
            WHERE id = %s
            """,
            (provider_message_id, message_id),
        )
        conn.execute(
            """
            UPDATE outreach_prospects p
            SET status = 'contacted', last_contacted_at = NOW(), updated_at = NOW()
            FROM outreach_messages m
            WHERE m.id = %s AND p.id = m.prospect_id
            """,
            (message_id,),
        )
        conn.commit()


def mark_message_failed(message_id: str, error: str) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE outreach_messages
            SET status = 'failed', html_body = html_body || %s
            WHERE id = %s
            """,
            (f"\n<!-- SEND ERROR: {error[:500]} -->", message_id),
        )
        conn.execute(
            """
            UPDATE outreach_prospects p
            SET status = 'eligible', updated_at = NOW()
            FROM outreach_messages m
            WHERE m.id = %s AND p.id = m.prospect_id
            """,
            (message_id,),
        )
        conn.commit()


def count_sent_today() -> int:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM outreach_messages
            WHERE sent_at >= date_trunc('day', NOW())
              AND status IN ('sent', 'delivered', 'opened', 'clicked')
            """
        ).fetchone()
    return int(row["count"] if row else 0)


def record_event(message_id: str | None, event_type: str, payload: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO outreach_events (message_id, event_type, event_json, occurred_at)
            VALUES (%s, %s, %s::jsonb, to_timestamp(%s))
            """,
            (
                message_id,
                event_type,
                json_dumps(payload),
                payload.get("timestamp", datetime.now(timezone.utc).timestamp()),
            ),
        )
        if message_id and event_type in {"delivered", "open", "click", "bounce", "dropped", "spamreport", "unsubscribe"}:
            status_map = {
                "open": "opened",
                "click": "clicked",
                "spamreport": "complaint",
                "unsubscribe": "unsubscribed",
            }
            conn.execute(
                "UPDATE outreach_messages SET status = %s WHERE id = %s",
                (status_map.get(event_type, event_type), message_id),
            )
        conn.commit()


def suppress_email(email: str, reason: str, source: str | None = None) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO outreach_suppressions(email, reason, source)
            VALUES (LOWER(%s), %s, %s)
            ON CONFLICT (email) DO UPDATE SET reason = EXCLUDED.reason, source = EXCLUDED.source
            """,
            (email.strip(), reason, source),
        )
        conn.commit()


def is_suppressed(email: str) -> bool:
    with connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM outreach_suppressions WHERE email = LOWER(%s)", (email,)
        ).fetchone()
    return row is not None


def create_custom_message(
    prospect_id: str,
    recipient_email: str,
    subject: str,
    text_body: str,
    html_body: str,
    catalog_version: str,
) -> str:
    """Insert an admin-authored custom message (does not change prospect status)."""
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO outreach_messages
                (prospect_id, catalog_version, offer_key, recipient_email,
                 subject, text_body, html_body, status)
            VALUES (%s, %s, 'custom', %s, %s, %s, %s, 'drafted')
            RETURNING id
            """,
            (prospect_id, catalog_version, recipient_email, subject, text_body, html_body),
        ).fetchone()
        conn.commit()
    return str(row["id"])


def mark_message_error(message_id: str, error: str) -> None:
    """Mark a message failed without altering the prospect's status."""
    with connection() as conn:
        conn.execute(
            "UPDATE outreach_messages SET status = 'failed', html_body = html_body || %s WHERE id = %s",
            (f"\n<!-- SEND ERROR: {error[:500]} -->", message_id),
        )
        conn.commit()


# -- Admin panel read queries --------------------------------------------

def get_prospect(prospect_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM outreach_prospects WHERE id = %s", (prospect_id,)).fetchone()
    return dict(row) if row else None


def list_prospects(status: str | None = None, search: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = %s")
        params.append(status)
    if search:
        clauses.append("(company_name ILIKE %s OR website ILIKE %s OR domain ILIKE %s OR contact_email ILIKE %s)")
        like = f"%{search}%"
        params.extend([like, like, like, like])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, company_name, website, domain, status, contact_email,
                   selected_offer_key, fit_score, last_contacted_at, updated_at
            FROM outreach_prospects
            {where}
            ORDER BY (fit_score IS NULL), fit_score DESC, updated_at DESC
            LIMIT %s
            """,
            tuple(params),
        ).fetchall()
    return list(rows)


def list_messages(status: str | None = None, prospect_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("m.status = %s")
        params.append(status)
    if prospect_id:
        clauses.append("m.prospect_id = %s")
        params.append(prospect_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT m.id, m.prospect_id, m.recipient_email, m.subject, m.status,
                   m.offer_key, m.provider_message_id, m.sent_at, m.created_at,
                   p.company_name
            FROM outreach_messages m
            LEFT JOIN outreach_prospects p ON p.id = m.prospect_id
            {where}
            ORDER BY m.created_at DESC
            LIMIT %s
            """,
            tuple(params),
        ).fetchall()
    return list(rows)


def get_message(message_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT m.*, p.company_name
            FROM outreach_messages m
            LEFT JOIN outreach_prospects p ON p.id = m.prospect_id
            WHERE m.id = %s
            """,
            (message_id,),
        ).fetchone()
    return dict(row) if row else None


def dashboard_stats() -> dict[str, Any]:
    with connection() as conn:
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM outreach_prospects GROUP BY status"
        ).fetchall()
        totals = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM outreach_prospects) AS prospects,
                (SELECT COUNT(*) FROM outreach_prospects WHERE status = 'eligible') AS eligible,
                (SELECT COUNT(*) FROM outreach_messages WHERE status IN ('sent','delivered','opened','clicked')) AS sent,
                (SELECT COUNT(*) FROM outreach_messages WHERE sent_at >= NOW() - INTERVAL '7 days') AS sent_7d,
                (SELECT COUNT(*) FROM outreach_suppressions) AS suppressions
            """
        ).fetchone()
        catalog = conn.execute(
            """
            SELECT catalog_version,
                   jsonb_array_length(catalog_json -> 'offers') AS offers,
                   created_at
            FROM outreach_catalog_versions
            WHERE active = TRUE
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    return {
        "by_status": {r["status"]: r["c"] for r in status_rows},
        "totals": dict(totals) if totals else {},
        "catalog": dict(catalog) if catalog else None,
    }


def message_status_counts() -> dict[str, int]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM outreach_messages GROUP BY status"
        ).fetchall()
    return {r["status"]: r["c"] for r in rows}
