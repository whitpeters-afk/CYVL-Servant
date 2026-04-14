"""
Morning briefing engine.

Pulls from all registered data sources, then uses Claude to generate a
unified briefing: prioritized emails, today's schedule, cross-referenced
attendees, flagged meeting requests, and draft replies.
"""
import os
from datetime import date, datetime, timezone, timedelta

import anthropic
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from sources.base import DataSource, SourceItem
from sources.gmail import GmailSource
from sources.google_calendar import GoogleCalendarSource

console = Console()

_BRIEFING_SYSTEM_PROMPT = """You are an AI Chief of Staff for a startup CEO.
Your job is to synthesize calendar and inbox data into a crisp, opinionated morning briefing.

Rules:
- Be direct. No filler. Every sentence should be actionable or informative.
- Flag cross-source signals loudly (email from today's meeting attendee = important).
- Triage ruthlessly: most email is noise. Surface what actually needs the CEO's attention.
- For draft replies, write something the CEO can send with zero edits — match their likely voice (busy, brief, decisive).
- For hidden meeting requests, always check the calendar data provided and say explicitly whether the proposed time is free or conflicts.
- Format output as clean markdown."""

_BRIEFING_USER_TEMPLATE = """Today is {today}. Tomorrow is {tomorrow}.

## Today's Calendar ({today_count} events)
{today_events}

## Tomorrow's Calendar ({tomorrow_count} events)
{tomorrow_events}

## Today's Meeting Attendees (for cross-reference)
{attendees}

## Unread Emails ({email_count} emails)
{email_data}

---

Generate a morning briefing with exactly these sections in order:

### 1. Top Priorities
3–5 bullets of the most important things to act on today. Be specific — name people, deadlines, amounts.

### 2. Today's Schedule
Chronological list of today's events. For any event whose attendees include someone who also sent an unread email, add 📅 after their name.

### 3. Tomorrow at a Glance
One line per event. Note any back-to-back blocks or conflicts.

### 4. Inbox Triage
Group emails into four buckets. For each email, one line: sender name, subject, one-sentence reason for its category. Flag emails from today's meeting attendees with 📅.

🔴 **Urgent** — needs action today
🟡 **Needs Reply** — requires a response (not necessarily today)
🔵 **FYI** — informational, no action needed
🗑 **Promotional / Noise** — can be ignored

### 5. Suggested Replies
For every email in the 🟡 Needs Reply bucket, write a ready-to-send reply draft. Format:

**Reply to: [Name] re: [Subject]**
> [Draft reply — 2–4 sentences, direct, no fluff]

### 6. Hidden Meeting Requests
Scan every email body for any request to schedule time ("let's meet", "can we jump on a call", "free Thursday?", etc.). For each one found:
- Quote the relevant sentence
- State the proposed time if mentioned
- Check it against today's and tomorrow's calendar and say: ✅ free or ⚠️ conflicts with [event name]

If no meeting requests found, write: "(none found)"

### 7. Flags & Conflicts
Any scheduling conflicts, overdue items, payment requests, or anything else that needs attention. If none, write: "(nothing to flag)"
"""


def _midnight_utc(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)


def _format_events(events: list[SourceItem]) -> str:
    if not events:
        return "(none)"
    lines = []
    for e in events:
        if e.timestamp:
            # All-day events land at midnight UTC; show "All day" for those
            if e.timestamp.hour == 0 and e.timestamp.minute == 0:
                ts = "All day"
            else:
                # Convert UTC → local for display
                local_ts = e.timestamp.astimezone()
                ts = local_ts.strftime("%-I:%M %p")
        else:
            ts = "All day"
        attendees = ", ".join(e.participants[:4]) if e.participants else "no attendees"
        lines.append(f"- {ts}: **{e.title}** — {attendees}")
    return "\n".join(lines)


def _format_emails(emails: list[SourceItem], attendee_emails: set[str]) -> str:
    if not emails:
        return "(no unread emails)"
    lines = []
    for e in emails:
        sender = e.participants[0] if e.participants else "unknown"
        attendee_flag = " 📅" if any(a in attendee_emails for a in e.participants) else ""
        ts = e.timestamp.astimezone().strftime("%b %-d %-I:%M %p") if e.timestamp else ""
        snippet = e.body[:200].replace("\n", " ").strip()
        lines.append(
            f"**[{e.id}] {e.title}**{attendee_flag}\n"
            f"  From: {sender} | {ts} | Priority: {e.priority}\n"
            f"  {snippet}"
        )
    return "\n\n".join(lines)


async def generate_briefing(extra_sources: list[DataSource] | None = None) -> str:
    """
    Generate the morning briefing.

    Pass additional DataSource instances via `extra_sources` to include
    Notion, HubSpot, Slack, etc. without changing this function.
    """
    gmail = GmailSource()
    calendar = GoogleCalendarSource()

    # Fetch in parallel
    import asyncio
    emails, all_events = await asyncio.gather(
        gmail.fetch_items(max_results=30),
        calendar.fetch_items(days_ahead=2),
    )

    today = date.today()
    tomorrow = today + timedelta(days=1)

    today_events = [
        e for e in all_events
        if e.timestamp and e.timestamp.astimezone().date() == today
    ]
    tomorrow_events = [
        e for e in all_events
        if e.timestamp and e.timestamp.astimezone().date() == tomorrow
    ]

    attendee_emails = {p for e in today_events for p in e.participants}

    extra_data = ""
    if extra_sources:
        for source in extra_sources:
            items = await source.fetch_items()
            if items:
                extra_data += f"\n## {source.name.title()} ({len(items)} items)\n"
                extra_data += "\n".join(f"- {i.title}: {i.body[:150]}" for i in items[:10])

    prompt = _BRIEFING_USER_TEMPLATE.format(
        today=today.strftime("%A, %B %-d, %Y"),
        tomorrow=tomorrow.strftime("%A, %B %-d, %Y"),
        today_count=len(today_events),
        today_events=_format_events(today_events),
        tomorrow_count=len(tomorrow_events),
        tomorrow_events=_format_events(tomorrow_events),
        attendees=", ".join(sorted(attendee_emails)) or "(none)",
        email_count=len(emails),
        email_data=_format_emails(emails, attendee_emails),
    )
    if extra_data:
        prompt += extra_data

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=[{
            "type": "text",
            "text": _BRIEFING_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


async def run_and_print(extra_sources: list[DataSource] | None = None) -> None:
    console.print("[bold blue]Fetching data and generating briefing…[/bold blue]")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    gmail = GmailSource()
    calendar = GoogleCalendarSource()

    import asyncio
    emails, all_events = await asyncio.gather(
        gmail.fetch_items(max_results=30),
        calendar.fetch_items(days_ahead=2),
    )

    today = date.today()
    tomorrow = today + timedelta(days=1)

    today_events = [
        e for e in all_events
        if e.timestamp and e.timestamp.astimezone().date() == today
    ]
    tomorrow_events = [
        e for e in all_events
        if e.timestamp and e.timestamp.astimezone().date() == tomorrow
    ]

    attendee_emails = {p for e in today_events for p in e.participants}

    extra_data = ""
    if extra_sources:
        for source in extra_sources:
            items = await source.fetch_items()
            if items:
                extra_data += f"\n## {source.name.title()} ({len(items)} items)\n"
                extra_data += "\n".join(f"- {i.title}: {i.body[:150]}" for i in items[:10])

    prompt = _BRIEFING_USER_TEMPLATE.format(
        today=today.strftime("%A, %B %-d, %Y"),
        tomorrow=tomorrow.strftime("%A, %B %-d, %Y"),
        today_count=len(today_events),
        today_events=_format_events(today_events),
        tomorrow_count=len(tomorrow_events),
        tomorrow_events=_format_events(tomorrow_events),
        attendees=", ".join(sorted(attendee_emails)) or "(none)",
        email_count=len(emails),
        email_data=_format_emails(emails, attendee_emails),
    )
    if extra_data:
        prompt += extra_data

    console.print("[bold blue]Streaming briefing…[/bold blue]\n")

    full_text = ""
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=[{
            "type": "text",
            "text": _BRIEFING_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        with Live(Markdown(""), console=console, refresh_per_second=8) as live:
            for text in stream.text_stream:
                full_text += text
                live.update(Markdown(full_text))
