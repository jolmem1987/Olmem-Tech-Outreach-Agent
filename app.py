from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from outreach.config import get_settings
from outreach.orchestrator import OutreachOrchestrator
from outreach.sender import process_sendgrid_events
from outreach.suppression import suppress_from_token

app = FastAPI(title="Olmem Outreach Agent", version="0.1.0")
settings = get_settings()


def verify_cron(authorization: str | None) -> None:
    if authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/")
def root() -> dict:
    return {
        "service": "olmem-outreach-agent",
        "status": "ok",
        "autonomous_send": settings.autonomous_send,
    }


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


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
    raw_body = await request.body()
    try:
        return process_sendgrid_events(request.headers, raw_body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe_get(token: str) -> str:
    try:
        suppress_from_token(token, reason="recipient_unsubscribe")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return "<h1>Unsubscribed</h1><p>This address will not receive further outreach.</p>"


@app.post("/api/unsubscribe/{token}", response_class=PlainTextResponse)
def unsubscribe_post(token: str) -> str:
    try:
        suppress_from_token(token, reason="one_click_unsubscribe")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return "Unsubscribed"
