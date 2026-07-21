from __future__ import annotations

import base64
import html
import json
from email.utils import parseaddr
from typing import Mapping

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from outreach.config import get_settings
from outreach.repository import record_event, suppress_email
from outreach.sync import sync_to_admin


class SendGridSender:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send(
        self,
        *,
        message_id: str,
        recipient_email: str,
        subject: str,
        text_body: str,
        html_body: str,
        unsubscribe_url: str,
    ) -> str | None:
        from_name, from_email = parseaddr(self.settings.sending_from_email)
        if not from_email:
            raise RuntimeError("SENDING_FROM_EMAIL must contain a valid email address")

        footer_text = (
            f"\n\n---\nThis is a commercial business outreach message from {self.settings.business_name}. "
            f"{self.settings.business_postal_address}\n"
            f"Unsubscribe: {unsubscribe_url}"
        )
        footer_html = (
            "<hr><p style=\"font-size:12px;color:#666\">"
            f"This is a commercial business outreach message from {html.escape(self.settings.business_name)}.<br>"
            f"{html.escape(self.settings.business_postal_address)}<br>"
            f"<a href=\"{html.escape(unsubscribe_url)}\">Unsubscribe</a>"
            "</p>"
        )

        payload = {
            "personalizations": [
                {
                    "to": [{"email": recipient_email}],
                    "custom_args": {"outreach_message_id": message_id},
                    "headers": {
                        "List-Unsubscribe": f"<{unsubscribe_url}>",
                        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                    },
                }
            ],
            "from": {"email": from_email, "name": from_name or self.settings.business_name},
            "reply_to": {"email": self.settings.reply_to_email},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text_body.rstrip() + footer_text},
                {"type": "text/html", "value": html_body.rstrip() + footer_html},
            ],
            "tracking_settings": {
                "open_tracking": {"enable": self.settings.track_opens},
                "click_tracking": {
                    "enable": self.settings.track_clicks,
                    "enable_text": self.settings.track_clicks,
                },
            },
            "categories": ["olmem-outreach"],
        }
        response = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {self.settings.sendgrid_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if response.status_code >= 300:
            raise RuntimeError(f"SendGrid rejected the message: {response.status_code} {response.text[:500]}")
        return response.headers.get("x-message-id")


def _load_sendgrid_public_key(value: str):
    raw = value.strip().encode("utf-8")
    if b"BEGIN PUBLIC KEY" in raw:
        return serialization.load_pem_public_key(raw)
    decoded = base64.b64decode(raw)
    try:
        return serialization.load_der_public_key(decoded)
    except ValueError:
        return serialization.load_pem_public_key(decoded)


def _verify_event_signature(headers: Mapping[str, str], raw_body: bytes) -> None:
    settings = get_settings()
    if not settings.verify_sendgrid_webhook:
        return
    if not settings.sendgrid_event_public_key:
        raise ValueError("SENDGRID_EVENT_PUBLIC_KEY is required when verification is enabled")
    signature_b64 = headers.get("x-twilio-email-event-webhook-signature")
    timestamp = headers.get("x-twilio-email-event-webhook-timestamp")
    if not signature_b64 or not timestamp:
        raise ValueError("Missing SendGrid webhook signature headers")
    public_key = _load_sendgrid_public_key(settings.sendgrid_event_public_key)
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise ValueError("SendGrid webhook public key is not an EC key")
    signature = base64.b64decode(signature_b64)
    # SendGrid libraries historically expose the P-256 signature as raw r||s bytes.
    # cryptography expects ASN.1 DER, so support both encodings.
    if len(signature) == 64:
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        signature = encode_dss_signature(r, s)
    signed_payload = timestamp.encode("utf-8") + raw_body
    try:
        public_key.verify(signature, signed_payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise ValueError("Invalid SendGrid webhook signature") from exc


def process_sendgrid_events(headers: Mapping[str, str], raw_body: bytes) -> dict:
    _verify_event_signature(headers, raw_body)
    try:
        events = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid SendGrid event payload") from exc
    if not isinstance(events, list):
        raise ValueError("SendGrid event payload must be a list")

    processed = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event", "unknown"))
        custom_args = event.get("outreach_message_id") or event.get("unique_args", {}).get(
            "outreach_message_id"
        )
        message_id = str(custom_args) if custom_args else None
        record_event(message_id, event_type, event)
        email = str(event.get("email", "")).lower().strip()
        if email and event_type in {"bounce", "dropped", "spamreport", "unsubscribe", "group_unsubscribe"}:
            suppress_email(email, reason=event_type, source="sendgrid_event")
        sync_to_admin(
            "email_engagement",
            {
                "message_id": message_id,
                "event": event_type,
                "email": email,
                "timestamp": event.get("timestamp"),
                "url": event.get("url"),
                "reason": event.get("reason"),
            },
        )
        processed += 1
    return {"processed": processed}
