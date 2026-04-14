"""
Gmail data source adapter.

Wraps the Gmail REST API and returns normalized SourceItems.
"""
import base64
import email as email_lib
from datetime import datetime, timezone
from typing import Any

from googleapiclient.discovery import build
from google.auth.transport.requests import AuthorizedSession

from auth.google_auth import get_credentials
from sources.base import DataSource, SourceItem


def _build_authorized_http(creds):
    """Return a requests-based authorized http transport for googleapiclient."""
    session = AuthorizedSession(creds)

    class _RequestsHttp:
        """Thin httplib2-compatible shim over requests.Session."""
        def request(self, uri, method="GET", body=None, headers=None, **kwargs):
            resp = session.request(method, uri, data=body, headers=headers, timeout=60)
            resp.status = resp.status_code
            return resp, resp.content

    return _RequestsHttp()


_URGENT_LABELS = {"IMPORTANT", "STARRED"}


def _decode_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _decode_body(part)
        if result:
            return result
    return ""


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _participants(headers: list[dict]) -> list[str]:
    addrs = []
    for field in ("from", "to", "cc"):
        val = _header(headers, field)
        if val:
            addrs.extend(a.strip() for a in val.split(","))
    return [a for a in addrs if a]


class GmailSource(DataSource):
    """Fetches emails from Gmail."""

    name = "gmail"

    def __init__(self) -> None:
        creds = get_credentials()
        self._service = build("gmail", "v1", http=_build_authorized_http(creds))

    async def fetch_items(
        self,
        max_results: int = 50,
        query: str = "is:inbox is:unread",
        metadata_only: bool = False,
        **kwargs,
    ) -> list[SourceItem]:
        """Fetch emails matching `query` sequentially."""
        list_resp = self._service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        msg_refs = list_resp.get("messages", [])
        if not msg_refs:
            return []

        msgs = []
        for ref in msg_refs:
            if metadata_only:
                msg = self._service.users().messages().get(
                    userId="me",
                    id=ref["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "To", "Date"],
                ).execute()
            else:
                msg = self._service.users().messages().get(
                    userId="me", id=ref["id"], format="full"
                ).execute()
            msgs.append(msg)

        return [self._to_source_item(msg) for msg in msgs]

    def _to_source_item(self, msg: dict[str, Any]) -> SourceItem:
        headers = msg.get("payload", {}).get("headers", [])
        labels = set(msg.get("labelIds", []))
        ts_ms = int(msg.get("internalDate", 0))
        timestamp = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) if ts_ms else None

        priority = "urgent" if labels & _URGENT_LABELS else "normal"

        # When fetched with format="metadata", payload has no body parts — use
        # the top-level snippet field instead of trying to decode an empty body.
        payload = msg.get("payload", {})
        has_body_parts = bool(payload.get("body", {}).get("data") or payload.get("parts"))
        if has_body_parts:
            body = _decode_body(payload)
        else:
            body = msg.get("snippet", "")

        return SourceItem(
            id=msg["id"],
            source=self.name,
            item_type="email",
            title=_header(headers, "subject") or "(no subject)",
            body=body,
            timestamp=timestamp,
            participants=_participants(headers),
            labels=list(labels),
            priority=priority,
            url=f"https://mail.google.com/mail/u/0/#inbox/{msg['id']}",
            raw=msg,
        )

    def get_thread(self, thread_id: str) -> list[SourceItem]:
        """Fetch all messages in a thread."""
        thread = (
            self._service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
        return [self._to_source_item(m) for m in thread.get("messages", [])]

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to_msg_id: str | None = None,
        thread_id: str | None = None,
    ) -> dict:
        """Send an email. Returns the sent message resource."""
        import email.mime.text
        mime = email.mime.text.MIMEText(body)
        mime["to"] = to
        mime["subject"] = subject
        if reply_to_msg_id:
            mime["In-Reply-To"] = reply_to_msg_id
            mime["References"] = reply_to_msg_id
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        send_body: dict = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id
        return (
            self._service.users()
            .messages()
            .send(userId="me", body=send_body)
            .execute()
        )
