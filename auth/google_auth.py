"""
Google OAuth 2.0 flow for Gmail + Calendar.

Run once via:  python -m auth.google_auth
Subsequent imports just call get_credentials() to load the cached token.
"""
import os
import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    # Gmail — read, compose, send
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    # Calendar — read and write events
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

_CREDENTIALS_DIR = Path(os.getenv("CREDENTIALS_DIR", "credentials"))
_CLIENT_SECRET = _CREDENTIALS_DIR / "client_secret.json"
_TOKEN_FILE = _CREDENTIALS_DIR / "token.json"


def get_credentials() -> Credentials:
    """Return valid Google credentials, refreshing or re-authorizing as needed."""
    creds: Credentials | None = None

    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CLIENT_SECRET.exists():
                raise FileNotFoundError(
                    f"Client secret not found at {_CLIENT_SECRET}. "
                    "Place your Google OAuth credentials file there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(_CLIENT_SECRET), SCOPES
            )
            # Opens browser for consent; binds to a random available port
            creds = flow.run_local_server(port=0, open_browser=True)

        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(creds.to_json())
        print(f"Token saved to {_TOKEN_FILE}")

    return creds


def main() -> None:
    """Entry point: run the OAuth consent flow and persist the token."""
    print("Starting Google OAuth flow...")
    print(f"Requesting scopes:\n  " + "\n  ".join(SCOPES))
    creds = get_credentials()
    info = json.loads(creds.to_json())
    print(f"\nAuthentication successful.")
    print(f"Authorized scopes: {info.get('scopes', SCOPES)}")
    print(f"Token stored at: {_TOKEN_FILE}")


if __name__ == "__main__":
    main()
