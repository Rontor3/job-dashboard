"""Create (never send) a Gmail draft with the tailored résumé attached.

Separate ``gmail.compose`` token from career_agent's read-only OTP token, so the
OTP reader keeps its narrower scope. One-time setup:

    PYTHONPATH=src python3 -m job_dashboard.apply.gmail_draft authorize

Sending stays a human action: this only places the draft in Gmail's Drafts.
"""
from __future__ import annotations

import base64
import pathlib
from email.message import EmailMessage

_DIR = pathlib.Path.home() / ".career_agent"
_CREDS = _DIR / "gmail_credentials.json"
_TOKEN = _DIR / "gmail_compose_token.json"  # not gmail_token*.json → OTP glob skips it
_SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


class DraftAuthError(RuntimeError):
    pass


def compose_message(to, subject, body, attachment: pathlib.Path | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    if attachment is not None:
        msg.add_attachment(attachment.read_bytes(), maintype="application",
                           subtype="pdf", filename=attachment.name)
    return msg


def create_draft(msg: EmailMessage, service=None) -> str:
    """Upload ``msg`` as a Gmail draft; returns the draft id."""
    service = service or _service()
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()["id"]


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    if not _TOKEN.exists():
        raise DraftAuthError("Gmail drafts not authorized — run: PYTHONPATH=src python3 "
                             "-m job_dashboard.apply.gmail_draft authorize")
    creds = Credentials.from_authorized_user_file(str(_TOKEN), _SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _TOKEN.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def authorize():
    from google_auth_oauthlib.flow import InstalledAppFlow
    creds = InstalledAppFlow.from_client_secrets_file(str(_CREDS), _SCOPES).run_local_server(port=0)
    _TOKEN.write_text(creds.to_json())
    print(f"[gmail-draft] token saved to {_TOKEN}")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["authorize"]:
        authorize()
    else:
        print(__doc__)
