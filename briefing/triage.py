"""
Inbox triage command.

Fetches unread Gmail (up to 20) and today's calendar, then uses Claude to
categorize every email into: Urgent / Needs Reply / FYI / Promotional/Noise.
Cross-references email senders against today's calendar attendees.
"""
import os
from datetime import date, datetime, timezone, timedelta

import anthropic
from rich.console import Console
from rich.markdown import Markdown

from sources.gmail import GmailSource
from sources.google_calendar import GoogleCalendarSource

console = Console()

_SYSTEM_PROMPT = """You are an AI Chief of Staff triaging email for a startup CEO.

Triage rules:
- ALWAYS Urgent: emails from investors, VCs, board members, city officials (Directors of Public Works, City Engineers, Mayors, Deputy Mayors, Procurement Officers, CAOs), state DOT contacts
- ALWAYS Urgent: subjects containing "contract", "LOI", "term sheet", "signature", "renewal", "cancel", "issue with"
- Needs Reply: partnership inquiries, inbound press/analyst, team blockers, legal/compliance
- FYI: usage reports, automated alerts, scheduling confirmations, internal updates
- Promotional/Noise: newsletters, marketing, vendor solicitations, conference invites with no existing relationship

Output format — exactly four sections with these headers:
🔴 **Urgent**
🟡 **Needs Reply**
🔵 **FYI**
🗑 **Promotional / Noise**

Under each header, one bullet per email:
- **Sender Name** — Subject — one-sentence reason. Append 📅 if sender is a today's-calendar attendee.

After the four buckets, add a section:
## Action Items
Bullet list of explicit asks, implicit deadlines, and commitments from Urgent and Needs Reply emails only. If none, write "(none)".
"""

_USER_TEMPLATE = """Today is {today}.

## Today's Calendar Attendees (for 📅 cross-reference)
{attendees}

## Unread Emails ({count} emails)
{emails}

Triage these emails now.
"""


def _fmt_emails(emails) -> str:
    lines = []
    for e in emails:
        sender = e.participants[0] if e.participants else "unknown"
        ts = e.timestamp.astimezone().strftime("%b %-d %-I:%M %p") if e.timestamp else ""
        snippet = e.body[:300].replace("\n", " ").strip()
        lines.append(f"**[{e.id}] {e.title}**\nFrom: {sender} | {ts}\n{snippet}")
    return "\n\n".join(lines) if lines else "(no unread emails)"


async def run_triage() -> None:
    console.print("[bold blue]Fetching inbox and calendar…[/bold blue]")

    gmail = GmailSource()
    calendar = GoogleCalendarSource()

    import asyncio
    emails, events = await asyncio.gather(
        gmail.fetch_items(max_results=20),
        calendar.fetch_items(days_ahead=1),
    )

    today = date.today()
    today_events = [
        e for e in events
        if e.timestamp and e.timestamp.astimezone().date() == today
    ]
    attendee_emails = {p for e in today_events for p in e.participants}

    prompt = _USER_TEMPLATE.format(
        today=today.strftime("%A, %B %-d, %Y"),
        attendees=", ".join(sorted(attendee_emails)) or "(none)",
        count=len(emails),
        emails=_fmt_emails(emails),
    )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    console.print("[bold blue]Categorizing…[/bold blue]\n")

    full_text = ""
    from rich.live import Live
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        with Live(Markdown(""), console=console, refresh_per_second=8) as live:
            for text in stream.text_stream:
                full_text += text
                live.update(Markdown(full_text))
