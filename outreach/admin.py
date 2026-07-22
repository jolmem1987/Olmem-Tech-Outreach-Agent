"""Admin panel routes (Olmem Outreach Console).

Server-rendered, password-protected UI mounted under /admin on the same
FastAPI app. Uses the post/redirect/get pattern with flash messages in the
query string, so no client-side JavaScript framework is needed.
"""
from __future__ import annotations

import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from outreach import adminui
from outreach.adminauth import (
    COOKIE_NAME,
    SESSION_TTL_SECONDS,
    admin_configured,
    check_password,
    is_authenticated,
    issue_session,
)
from outreach.config import get_settings
from outreach.criteria import get_criteria, reset_criteria, save_criteria, total_possible
from outreach.db import init_db
from outreach.orchestrator import OutreachOrchestrator
from outreach.repository import (
    dashboard_stats,
    get_message,
    get_prospect,
    list_messages,
    list_prospects,
    message_status_counts,
)

router = APIRouter()

_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if not _schema_ready:
        init_db()
        _schema_ready = True


def _html(body: str) -> HTMLResponse:
    return HTMLResponse(body)


def _redirect(path: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    params = {}
    if msg:
        params["msg"] = msg
    if err:
        params["err"] = err
    url = path + (("?" + urlencode(params)) if params else "")
    return RedirectResponse(url, status_code=303)


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/admin/login", status_code=303)


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


# -- Auth -----------------------------------------------------------------

@router.get("/admin/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    if is_authenticated(request):
        return RedirectResponse("/admin", status_code=303)
    return _html(adminui.login_page(configured=admin_configured()))


@router.post("/admin/login")
def login_submit(request: Request, password: str = Form("")) -> RedirectResponse | HTMLResponse:
    if not admin_configured():
        return _html(adminui.login_page(configured=False))
    if not check_password(password):
        return _html(adminui.login_page(error="Incorrect password.", configured=True))
    resp = RedirectResponse("/admin", status_code=303)
    secure = get_settings().app_base_url.startswith("https")
    resp.set_cookie(
        COOKIE_NAME, issue_session(), max_age=SESSION_TTL_SECONDS,
        httponly=True, samesite="lax", secure=secure, path="/",
    )
    return resp


@router.post("/admin/logout")
def logout() -> RedirectResponse:
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


# -- Dashboard ------------------------------------------------------------

@router.get("/admin", response_class=HTMLResponse)
def dashboard(request: Request, msg: str | None = Query(None), err: str | None = Query(None)) -> HTMLResponse | RedirectResponse:
    if not is_authenticated(request):
        return _login_redirect()
    _ensure_schema()
    return _html(adminui.dashboard_page(dashboard_stats(), msg=msg, err=err))


@router.post("/admin/jobs/{job}")
def run_job(request: Request, job: str) -> RedirectResponse:
    if not is_authenticated(request):
        return _login_redirect()
    method = {
        "catalog": "refresh_catalog",
        "discover": "discover_prospects",
        "research": "research_and_score",
        "send": "send_eligible",
    }.get(job)
    if not method:
        return _redirect("/admin", err="Unknown job.")
    try:
        result = getattr(OutreachOrchestrator(), method)()
        return _redirect("/admin", msg=f"Job '{job}' finished: {result}")
    except Exception as exc:  # noqa: BLE001 - surface any job failure to the admin
        return _redirect("/admin", err=f"Job '{job}' failed: {exc}")


# -- Prospects ------------------------------------------------------------

@router.get("/admin/prospects", response_class=HTMLResponse)
def prospects(
    request: Request,
    q: str = Query(""),
    status: str = Query(""),
    msg: str | None = Query(None),
    err: str | None = Query(None),
) -> HTMLResponse | RedirectResponse:
    if not is_authenticated(request):
        return _login_redirect()
    _ensure_schema()
    rows = list_prospects(status=status or None, search=q or None)
    return _html(adminui.prospects_page(rows, status=status, search=q, msg=msg, err=err))


@router.get("/admin/prospects/{prospect_id}", response_class=HTMLResponse)
def prospect_detail(
    request: Request, prospect_id: str, msg: str | None = Query(None), err: str | None = Query(None)
) -> HTMLResponse | RedirectResponse:
    if not is_authenticated(request):
        return _login_redirect()
    if not _valid_uuid(prospect_id):
        return _redirect("/admin/prospects", err="Invalid prospect id.")
    _ensure_schema()
    prospect = get_prospect(prospect_id)
    if not prospect:
        return _redirect("/admin/prospects", err="Prospect not found.")
    messages = list_messages(prospect_id=prospect_id)
    return _html(adminui.prospect_detail_page(prospect, messages, msg=msg, err=err))


@router.post("/admin/prospects/{prospect_id}/send-draft")
def send_draft(request: Request, prospect_id: str) -> RedirectResponse:
    if not is_authenticated(request):
        return _login_redirect()
    if not _valid_uuid(prospect_id):
        return _redirect("/admin/prospects", err="Invalid prospect id.")
    _ensure_schema()
    result = OutreachOrchestrator().send_prospect_now(prospect_id)
    dest = f"/admin/prospects/{prospect_id}"
    if result.get("ok"):
        return _redirect(dest, msg=f"Sent to {result.get('recipient')}.")
    return _redirect(dest, err=result.get("error", "Send failed."))


@router.post("/admin/prospects/{prospect_id}/send-custom")
def send_custom(
    request: Request,
    prospect_id: str,
    recipient: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
) -> RedirectResponse:
    if not is_authenticated(request):
        return _login_redirect()
    if not _valid_uuid(prospect_id):
        return _redirect("/admin/prospects", err="Invalid prospect id.")
    _ensure_schema()
    result = OutreachOrchestrator().send_custom(prospect_id, subject, body, recipient=recipient or None)
    dest = f"/admin/prospects/{prospect_id}"
    if result.get("ok"):
        return _redirect(dest, msg=f"Custom email sent to {result.get('recipient')}.")
    return _redirect(dest, err=result.get("error", "Send failed."))


# -- Emails ---------------------------------------------------------------

@router.get("/admin/emails", response_class=HTMLResponse)
def emails(
    request: Request, status: str = Query(""), msg: str | None = Query(None), err: str | None = Query(None)
) -> HTMLResponse | RedirectResponse:
    if not is_authenticated(request):
        return _login_redirect()
    _ensure_schema()
    rows = list_messages(status=status or None)
    return _html(adminui.emails_page(rows, message_status_counts(), status=status, msg=msg, err=err))


@router.get("/admin/emails/{message_id}", response_class=HTMLResponse)
def email_detail(request: Request, message_id: str) -> HTMLResponse | RedirectResponse:
    if not is_authenticated(request):
        return _login_redirect()
    if not _valid_uuid(message_id):
        return _redirect("/admin/emails", err="Invalid message id.")
    _ensure_schema()
    message = get_message(message_id)
    if not message:
        return _redirect("/admin/emails", err="Email not found.")
    return _html(adminui.email_detail_page(message))


# -- Criteria -------------------------------------------------------------

@router.get("/admin/criteria", response_class=HTMLResponse)
def criteria_form(
    request: Request, reset: str | None = Query(None), msg: str | None = Query(None), err: str | None = Query(None)
) -> HTMLResponse | RedirectResponse:
    if not is_authenticated(request):
        return _login_redirect()
    _ensure_schema()
    if reset:
        reset_criteria()
        return _redirect("/admin/criteria", msg="Criteria reset to defaults.")
    criteria = get_criteria()
    return _html(adminui.criteria_page(criteria, total_possible(criteria), msg=msg, err=err))


@router.post("/admin/criteria")
def criteria_save(
    request: Request,
    min_fit_score: str = Form("0"),
    min_problem_evidence: str = Form("0"),
    min_offer_alignment: str = Form("0"),
    min_contact_quality: str = Form("0"),
    daily_send_limit: str = Form("1"),
    contact_cooldown_days: str = Form("0"),
    w_problem_evidence: str = Form("0"),
    w_offer_alignment: str = Form("0"),
    w_customer_fit: str = Form("0"),
    w_contact_quality: str = Form("0"),
    w_timing_signal: str = Form("0"),
    autonomous_send: str | None = Form(None),
    allow_named_public_emails: str | None = Form(None),
    discovery_regions: str = Form(""),
) -> RedirectResponse:
    if not is_authenticated(request):
        return _login_redirect()
    _ensure_schema()
    payload = {
        "min_fit_score": min_fit_score,
        "min_problem_evidence": min_problem_evidence,
        "min_offer_alignment": min_offer_alignment,
        "min_contact_quality": min_contact_quality,
        "daily_send_limit": daily_send_limit,
        "contact_cooldown_days": contact_cooldown_days,
        "autonomous_send": autonomous_send == "true",
        "allow_named_public_emails": allow_named_public_emails == "true",
        "discovery_regions": discovery_regions,
        "weights": {
            "problem_evidence": w_problem_evidence,
            "offer_alignment": w_offer_alignment,
            "customer_fit": w_customer_fit,
            "contact_quality": w_contact_quality,
            "timing_signal": w_timing_signal,
        },
    }
    try:
        save_criteria(payload)
        return _redirect("/admin/criteria", msg="Criteria saved.")
    except Exception as exc:  # noqa: BLE001
        return _redirect("/admin/criteria", err=f"Could not save: {exc}")
