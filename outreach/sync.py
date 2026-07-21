from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from outreach.config import get_settings


def sync_to_admin(event_type: str, payload: dict[str, Any]) -> bool:
    settings = get_settings()
    if not settings.lead_sync_url or not settings.lead_sync_secret:
        return False
    body = json.dumps(
        {"event_type": event_type, "payload": payload},
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    signature = hmac.new(
        settings.lead_sync_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    try:
        response = httpx.post(
            settings.lead_sync_url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Olmem-Signature": f"sha256={signature}",
            },
            timeout=12,
        )
        return response.status_code < 300
    except httpx.HTTPError:
        return False
