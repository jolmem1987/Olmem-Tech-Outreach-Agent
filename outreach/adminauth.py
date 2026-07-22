"""Password login and a stateless signed-cookie session for the admin panel.

The panel runs on serverless (Vercel) with no session store, so the session is
a self-contained cookie: ``<expiry_ts>.<hmac>`` signed with ``TOKEN_SECRET``.
No secrets are stored client-side beyond the signature. Access requires
``ADMIN_PASSWORD`` to be configured; if it is unset the panel refuses all
logins (fail closed).
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Request

from outreach.config import get_settings

COOKIE_NAME = "olmem_admin"
SESSION_TTL_SECONDS = 12 * 60 * 60  # 12 hours


def _sign(expiry: int) -> str:
    settings = get_settings()
    msg = f"admin:{expiry}".encode("utf-8")
    return hmac.new(settings.token_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def issue_session() -> str:
    expiry = int(time.time()) + SESSION_TTL_SECONDS
    return f"{expiry}.{_sign(expiry)}"


def verify_session(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expiry_str, signature = token.rsplit(".", 1)
    try:
        expiry = int(expiry_str)
    except ValueError:
        return False
    if expiry < int(time.time()):
        return False
    return hmac.compare_digest(signature, _sign(expiry))


def check_password(candidate: str) -> bool:
    settings = get_settings()
    if not settings.admin_password:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), settings.admin_password.encode("utf-8"))


def is_authenticated(request: Request) -> bool:
    return verify_session(request.cookies.get(COOKIE_NAME))


def admin_configured() -> bool:
    return bool(get_settings().admin_password)
