from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from outreach.config import get_settings
from outreach.repository import suppress_email


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().token_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def make_unsubscribe_token(email: str) -> str:
    return _fernet().encrypt(email.lower().strip().encode("utf-8")).decode("ascii")


def suppress_from_token(token: str, reason: str) -> str:
    try:
        email = _fernet().decrypt(token.encode("ascii")).decode("utf-8").lower().strip()
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise ValueError("Invalid unsubscribe token") from exc
    if "@" not in email:
        raise ValueError("Invalid unsubscribe token")
    suppress_email(email, reason=reason, source="unsubscribe_endpoint")
    return email
