"""One-off SendGrid integration check.

SendGrid's onboarding asks for a real API call before it will mark the
integration verified. The application does not use the `sendgrid` SDK - it posts
to the same v3 endpoint with httpx (see outreach/sender.py) - so this script
mirrors that request rather than adding a dependency.

It deliberately avoids outreach.config: no database, no OpenAI key, and no
Settings validation, so it runs before the rest of the stack is configured.

Usage:
    python scripts/verify_sendgrid.py                 # sends to REPLY_TO_EMAIL
    python scripts/verify_sendgrid.py you@example.com
"""

from __future__ import annotations

import sys
from email.utils import parseaddr
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def load_env_file() -> dict[str, str]:
    """Read .env.local, falling back to .env. Values are not exported."""
    for name in (".env.local", ".env"):
        path = ROOT / name
        if not path.exists():
            continue
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
        print(f"Loaded {name}")
        return values
    sys.exit("No .env.local or .env found next to this repo's pyproject.toml.")


def main() -> int:
    env = load_env_file()
    api_key = env.get("SENDGRID_API_KEY", "")
    if not api_key or api_key == "FILL_IN":
        sys.exit("SENDGRID_API_KEY is not set. Paste the restricted Mail Send key first.")

    from_name, from_email = parseaddr(env.get("SENDING_FROM_EMAIL", ""))
    if not from_email:
        sys.exit("SENDING_FROM_EMAIL must contain a valid address, e.g. Name <a@b.com>.")

    recipient = sys.argv[1] if len(sys.argv) > 1 else env.get("REPLY_TO_EMAIL", "")
    if not recipient:
        sys.exit("Pass a recipient address, or set REPLY_TO_EMAIL.")

    print(f"Sending test message: {from_email} -> {recipient}")

    response = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "personalizations": [{"to": [{"email": recipient}]}],
            "from": {"email": from_email, "name": from_name or "Olmem Technical Solutions"},
            "reply_to": {"email": env.get("REPLY_TO_EMAIL", from_email)},
            "subject": "Olmem outreach agent - SendGrid integration test",
            "content": [
                {
                    "type": "text/plain",
                    "value": (
                        "This is a one-off integration test from the Olmem outreach agent.\n"
                        "If you are reading this, the API key and sending identity both work."
                    ),
                }
            ],
            "categories": ["olmem-outreach-test"],
        },
        timeout=20,
    )

    if response.status_code < 300:
        print(f"OK ({response.status_code}). x-message-id: {response.headers.get('x-message-id')}")
        print("Now click 'Verify Integration' in the SendGrid console.")
        return 0

    print(f"FAILED ({response.status_code})")
    print(response.text[:800])
    if response.status_code == 401:
        print("\n-> The API key is wrong, revoked, or was copied with whitespace.")
    elif response.status_code == 403:
        print(
            "\n-> Either the key lacks Mail Send permission, or the from address is not a "
            f"verified sender identity. Authenticate the domain of {from_email} under "
            "Settings > Sender Authentication first."
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
