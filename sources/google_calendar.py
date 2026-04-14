"""
Google Calendar data source adapter.

Wraps the Calendar REST API and returns normalized SourceItems.
"""
from datetime import datetime, timezone, timedelta
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
            resp = session.request(method, uri, data=body, headers=headers, timeout=30)
            resp.status = resp.status_code
            return resp, resp.content

    return _RequestsHttp()


def _parse_dt(dt_obj: dict) -> datetime | None:
    """Parse a Calendar dateTime or date dict into a UTC datetime."""
    if not dt_obj:
        return None
    if "dateTime" in dt_obj:
        return datetime.fromisoformat(dt_obj["dateTime"]).astimezone(timezone.utc)
    if "date" in dt_obj:
        return datetime.fromisoformat(dt_obj["date"]).replace(tzinfo=timezone.utc)
    return None


def _attendee_emails(event: dict) -> list[str]:
    return [a["email"] for a in event.get("attendees", []) if "email" in a]


class GoogleCalendarSource(DataSource):
    """Fetches events from Google Calendar."""

    name = "google_calendar"

    def __init__(self) -> None:
        creds = get_credentials()
        self._service = build("calendar", "v3", http=_build_authorized_http(creds))

    async def fetch_items(
        self,
        max_results: int = 50,
        days_ahead: int = 1,
        calendar_id: str = "primary",
        **kwargs,
    ) -> list[SourceItem]:
        """Fetch calendar events for the next `days_ahead` days."""
        now = datetime.now(tz=timezone.utc)
        result = (
            self._service.events()
            .list(
                calendarId=calendar_id,
                timeMin=now.isoformat(),
                timeMax=(now + timedelta(days=days_ahead)).isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return [self._to_source_item(e) for e in result.get("items", [])]

    def _to_source_item(self, event: dict[str, Any]) -> SourceItem:
        start = _parse_dt(event.get("start", {}))
        return SourceItem(
            id=event["id"],
            source=self.name,
            item_type="event",
            title=event.get("summary", "(no title)"),
            body=event.get("description", ""),
            timestamp=start,
            participants=_attendee_emails(event),
            labels=[event.get("status", "confirmed")],
            priority="normal",
            url=event.get("htmlLink", ""),
            raw=event,
        )

    def check_conflicts(self, proposed_start: datetime, proposed_end: datetime, calendar_id: str = "primary") -> list[SourceItem]:
        """Return any existing events that overlap the proposed time window."""
        result = (
            self._service.events()
            .list(
                calendarId=calendar_id,
                timeMin=proposed_start.isoformat(),
                timeMax=proposed_end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return [self._to_source_item(e) for e in result.get("items", [])]

    def find_events_by_keyword(
        self,
        keyword: str,
        days_ahead: int = 30,
        calendar_id: str = "primary",
    ) -> list[SourceItem]:
        """Return upcoming events whose title contains `keyword` (case-insensitive)."""
        now = datetime.now(tz=timezone.utc)
        result = (
            self._service.events()
            .list(
                calendarId=calendar_id,
                timeMin=now.isoformat(),
                timeMax=(now + timedelta(days=days_ahead)).isoformat(),
                q=keyword,
                singleEvents=True,
                orderBy="startTime",
                maxResults=10,
            )
            .execute()
        )
        return [self._to_source_item(e) for e in result.get("items", [])]

    def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str = "",
        attendees: list[str] | None = None,
        calendar_id: str = "primary",
    ) -> dict:
        """Create a calendar event and return the created event resource."""
        body: dict = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees]
        return (
            self._service.events()
            .insert(calendarId=calendar_id, body=body)
            .execute()
        )

    def update_event(
        self,
        event_id: str,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
    ) -> dict:
        """Update the start/end time of an existing event."""
        body = {
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
        return (
            self._service.events()
            .patch(calendarId=calendar_id, eventId=event_id, body=body)
            .execute()
        )

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> None:
        """Delete a calendar event by ID."""
        self._service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
