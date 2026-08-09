"""The per-prospect research and delete controls.

`adminui` is pure rendering - no config, no database - so these run anywhere.
What matters here is that the delete control disappears once a prospect has been
emailed: outreach_messages cascades on delete, so offering the button would be
offering to erase the record of what was sent and when.
"""
from __future__ import annotations

from outreach import adminui


PROSPECT_ID = "0e3f5a4c-1111-2222-3333-444455556666"


def discovered() -> dict:
    return {
        "id": PROSPECT_ID,
        "company_name": "Alder Creek Tree Service",
        "domain": "aldercreek.example",
        "website": "https://aldercreek.example",
        "status": "discovered",
    }


def researched() -> dict:
    return {
        **discovered(),
        "status": "rejected",
        "fit_score": 71,
        "selected_offer_key": "contractor-website",
        "research_json": {"observed_problems": ["No quote form"], "evidence": []},
        "fit_json": {"components": {}, "rationale": "why", "evidence": []},
    }


def sent_message() -> dict:
    return {
        "id": "6f1b2c3d-aaaa-bbbb-cccc-ddddeeeeffff",
        "subject": "Subject",
        "offer_key": "contractor-website",
        "status": "sent",
        "created_at": "2026-08-01",
    }


def test_discovered_prospect_offers_research_and_delete() -> None:
    page = adminui.prospect_detail_page(discovered(), [])
    assert f"/admin/prospects/{PROSPECT_ID}/research" in page
    assert f"/admin/prospects/{PROSPECT_ID}/delete" in page
    assert "Research &amp; score now" in page


def test_already_researched_prospect_offers_a_re_research() -> None:
    page = adminui.prospect_detail_page(researched(), [])
    assert "Re-research &amp; score" in page
    # A rejected prospect is the most likely thing to want removed.
    assert f"/admin/prospects/{PROSPECT_ID}/delete" in page


def test_delete_is_withheld_once_an_email_exists() -> None:
    page = adminui.prospect_detail_page(researched(), [sent_message()])
    assert f"/admin/prospects/{PROSPECT_ID}/delete" not in page
    assert "cannot be deleted" in page
    # Research is still offered - re-scoring a contacted prospect is harmless.
    assert f"/admin/prospects/{PROSPECT_ID}/research" in page


def test_delete_is_withheld_when_last_contacted_is_set_without_messages() -> None:
    """last_contacted_at is set by the send path; messages may be filtered out of
    the view. Either alone must be enough to withhold the button."""
    page = adminui.prospect_detail_page({**researched(), "last_contacted_at": "2026-08-01"}, [])
    assert f"/admin/prospects/{PROSPECT_ID}/delete" not in page


def test_delete_confirmation_names_the_company() -> None:
    page = adminui.prospect_detail_page(discovered(), [])
    assert "Delete Alder Creek Tree Service permanently?" in page


def test_company_name_is_escaped_in_the_confirmation() -> None:
    """The confirm() string is built from company_name inside an HTML attribute."""
    hostile = {**discovered(), "company_name": "O'Brien & Sons <script>"}
    page = adminui.prospect_detail_page(hostile, [])
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
