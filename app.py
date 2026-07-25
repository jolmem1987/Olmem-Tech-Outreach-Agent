from __future__ import annotations

import traceback

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

app = FastAPI(title="Olmem Outreach Agent", version="0.1.0")

# Boot guard. Settings validation and the outreach imports both run at module
# import time, so a missing env var or an uninstalled dependency used to kill the
# import outright - which Vercel reports only as an opaque
# FUNCTION_INVOCATION_FAILED with the real cause buried in a truncated log line.
# Capturing it here keeps the function importable so /api/health can name the
# actual problem.
BOOT_ERROR: str | None = None
try:
    from outreach.admin import router as admin_router
    from outreach.config import get_settings
    from outreach.orchestrator import OutreachOrchestrator
    from outreach.sender import process_sendgrid_events
    from outreach.suppression import suppress_from_token

    settings = get_settings()
    app.include_router(admin_router)
except Exception as exc:  # noqa: BLE001 - any boot failure must stay reportable
    BOOT_ERROR = f"{type(exc).__name__}: {exc}"
    BOOT_TRACEBACK = traceback.format_exc()


def require_boot() -> None:
    if BOOT_ERROR:
        raise HTTPException(status_code=503, detail=f"Application failed to start. {BOOT_ERROR}")


def verify_cron(authorization: str | None) -> None:
    require_boot()
    if authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/")
def root() -> dict:
    require_boot()
    return {
        "service": "olmem-outreach-agent",
        "status": "ok",
        "autonomous_send": settings.autonomous_send,
    }


@app.get("/api/health")
def health() -> JSONResponse:
    if BOOT_ERROR:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": BOOT_ERROR, "traceback": BOOT_TRACEBACK.splitlines()[-12:]},
        )
    return JSONResponse(content={"ok": True})


@app.get("/api/cron/catalog")
def cron_catalog(authorization: str | None = Header(default=None)) -> dict:
    verify_cron(authorization)
    return OutreachOrchestrator().refresh_catalog()


@app.get("/api/cron/discover")
def cron_discover(authorization: str | None = Header(default=None)) -> dict:
    verify_cron(authorization)
    return OutreachOrchestrator().discover_prospects()


@app.get("/api/cron/research")
def cron_research(authorization: str | None = Header(default=None)) -> dict:
    verify_cron(authorization)
    return OutreachOrchestrator().research_and_score()


@app.get("/api/cron/send")
def cron_send(authorization: str | None = Header(default=None)) -> dict:
    verify_cron(authorization)
    return OutreachOrchestrator().send_eligible()


@app.post("/api/webhooks/sendgrid/events")
async def sendgrid_events(request: Request) -> dict:
    require_boot()
    raw_body = await request.body()
    try:
        return process_sendgrid_events(request.headers, raw_body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe_get(token: str) -> str:
    require_boot()
    try:
        suppress_from_token(token, reason="recipient_unsubscribe")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return "<h1>Unsubscribed</h1><p>This address will not receive further outreach.</p>"


@app.post("/api/unsubscribe/{token}", response_class=PlainTextResponse)
def unsubscribe_post(token: str) -> str:
    require_boot()
    try:
        suppress_from_token(token, reason="one_click_unsubscribe")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return "Unsubscribed"
