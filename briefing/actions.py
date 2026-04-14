"""
Interactive action commands.

    python main.py replies      — review AI-drafted replies, send or skip each one
    python main.py scan-events  — review detected meeting requests, add to calendar or skip
"""
import asyncio
import json
import os
import subprocess
import tempfile
from datetime import date, datetime, timezone, timedelta

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from sources.gmail import GmailSource
from sources.google_calendar import GoogleCalendarSource

console = Console()


# ── Shared helpers ────────────────────────────────────────────────────────────

def _parse_json_response(raw: str) -> list | None:
    """Strip optional markdown fences and parse JSON. Returns None on failure."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Could not parse Claude response as JSON ({exc}):[/red]\n{text}")
        return None


def _open_in_editor(initial_text: str) -> str:
    """Open text in $EDITOR. Falls back to inline terminal input."""
    editor = os.environ.get("EDITOR", "")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(initial_text)
        path = f.name
    try:
        if editor:
            subprocess.call([editor, path])
            with open(path) as f:
                return f.read().strip()
        else:
            console.print("[dim]$EDITOR not set. Type your reply. End with a line containing only '---'[/dim]")
            lines = []
            while True:
                line = input()
                if line.strip() == "---":
                    break
                lines.append(line)
            return "\n".join(lines)
    finally:
        os.unlink(path)


def _format_emails_for_action(emails) -> str:
    lines = []
    for e in emails:
        sender = e.participants[0] if e.participants else "unknown"
        ts = e.timestamp.astimezone().strftime("%b %-d %-I:%M %p") if e.timestamp else ""
        body = e.body[:800].replace("\n", " ").strip()
        lines.append(
            f"**[{e.id}] {e.title}**\n"
            f"  From: {sender} | {ts}\n"
            f"  {body}"
        )
    return "\n\n".join(lines)


def _format_events_brief(events) -> str:
    if not events:
        return "(none)"
    lines = []
    for e in events:
        if e.timestamp:
            local_ts = e.timestamp.astimezone()
            ts = local_ts.strftime("%A %-I:%M %p") if local_ts.hour or local_ts.minute else "All day"
        else:
            ts = "All day"
        lines.append(f"- {ts}: {e.title}")
    return "\n".join(lines)


# ── Replies command ───────────────────────────────────────────────────────────

_REPLIES_SYSTEM = """\
You are an AI Chief of Staff for a startup CEO.
Analyze the provided emails and identify which ones need a reply from the CEO.
Return a JSON array ONLY — no prose, no markdown fences.

For each email that genuinely needs a reply include:
{
  "email_id": "<gmail message id from the [id] prefix>",
  "to": "<reply-to email address>",
  "subject": "<Re: original subject>",
  "draft_reply": "<complete ready-to-send reply — 2–4 sentences, direct, decisive>",
  "reason": "<one sentence why this needs a reply>"
}

Exclude: newsletters, automated notifications, CC'd FYIs, promotional mail.
Match a busy startup CEO's voice: brief, direct, no filler."""

_REPLIES_USER = """\
Today is {today}.

## Unread Emails ({count} emails)
{email_data}

Identify which emails need a reply and write ready-to-send drafts.
Return a JSON array only."""


async def run_replies() -> None:
    """Interactive reply review: show each drafted reply, let CEO send/edit/skip."""
    console.print("[bold blue]Fetching emails…[/bold blue]")
    gmail = GmailSource()
    emails = await gmail.fetch_items(max_results=30)

    if not emails:
        console.print("No unread emails.")
        return

    email_data = _format_emails_for_action(emails)
    today = date.today().strftime("%A, %B %-d, %Y")

    console.print("[bold blue]Asking Claude which emails need replies…[/bold blue]\n")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=_REPLIES_SYSTEM,
        messages=[{
            "role": "user",
            "content": _REPLIES_USER.format(today=today, count=len(emails), email_data=email_data),
        }],
    )

    items = _parse_json_response(response.content[0].text)
    if items is None:
        return

    if not items:
        console.print("[green]No emails need a reply right now.[/green]")
        return

    console.print(f"[bold]{len(items)} email(s) need a reply.[/bold]\n")
    email_map = {e.id: e for e in emails}
    sent = skipped = 0

    for idx, item in enumerate(items, 1):
        email_id = item.get("email_id", "")
        original = email_map.get(email_id)
        draft = item.get("draft_reply", "")
        reason = item.get("reason", "")

        console.print(Panel(
            f"[bold]To:[/bold]      {item.get('to', '?')}\n"
            f"[bold]Subject:[/bold] {item.get('subject', '')}\n"
            f"[bold]Why:[/bold]     {reason}\n\n"
            f"[bold]Draft:[/bold]\n{draft}",
            title=f"[cyan]Reply {idx}/{len(items)}[/cyan]",
            expand=False,
        ))

        choice = Prompt.ask(
            "[bold]Action[/bold]",
            choices=["send", "edit", "skip"],
            default="skip",
        )

        if choice == "skip":
            skipped += 1
            continue

        if choice == "edit":
            draft = _open_in_editor(draft)
            if not draft:
                console.print("[yellow]Empty reply — skipped.[/yellow]")
                skipped += 1
                continue
            console.print(Panel(draft, title="[yellow]Edited reply[/yellow]", expand=False))
            confirm = Prompt.ask("Send this?", choices=["yes", "no"], default="yes")
            if confirm == "no":
                skipped += 1
                continue

        thread_id = original.raw.get("threadId") if original else None
        gmail.send_message(
            to=item["to"],
            subject=item.get("subject", ""),
            body=draft,
            reply_to_msg_id=email_id if email_id else None,
            thread_id=thread_id,
        )
        console.print("[green]✓ Sent[/green]")
        sent += 1

    console.print(f"\n[bold]Done.[/bold]  Sent: {sent}   Skipped: {skipped}")


# ── Scan-events command ───────────────────────────────────────────────────────

_SCAN_SYSTEM = """\
You are an AI Chief of Staff for a startup CEO.
Scan the provided emails for meeting requests, scheduling asks, or time commitments.
Return a JSON array ONLY — no prose, no markdown fences.

For each meeting request found include:
{
  "email_id": "<gmail message id from the [id] prefix>",
  "from_name": "<sender name or email>",
  "source_quote": "<exact text from the email that contains the scheduling ask>",
  "title": "<descriptive event title, e.g. 'Intro call with Jane re: Series A'>",
  "description": "<1–2 sentence context for the calendar event>",
  "proposed_start_iso": "<ISO 8601 datetime with timezone offset, or null if unclear>",
  "proposed_end_iso": "<ISO 8601 datetime with timezone offset, or null if unclear>",
  "duration_minutes": 60,
  "attendees": ["<email addresses of relevant participants>"],
  "is_time_clear": true,
  "is_reschedule": false,
  "original_event_title": "<title of the existing event being rescheduled, or null>"
}

Set is_time_clear to false when no specific date/time is mentioned.
Set is_reschedule to true when the email is asking to move/reschedule an EXISTING meeting
  (phrases like "can we move our X to…", "reschedule our call", "change the time of our meeting").
  In that case set original_event_title to your best guess at the existing event's title.
Default duration_minutes to 30 for quick syncs, 60 otherwise.
Return [] if no meeting requests are found."""

_SCAN_USER = """\
Today is {today}.

## Existing Calendar (next 7 days)
{events}

## Emails to Scan ({count} emails)
{email_data}

Find all meeting requests and scheduling asks. Return a JSON array only."""


def _prompt_for_datetime(prompt_label: str) -> datetime | None:
    """Prompt the user to enter a datetime. Returns None if they skip."""
    console.print(f"[yellow]{prompt_label}[/yellow]")
    console.print("[dim]Format: YYYY-MM-DD HH:MM  (local time, 24h). Leave blank to skip.[/dim]")
    raw = input("> ").strip()
    if not raw:
        return None
    try:
        naive = datetime.strptime(raw, "%Y-%m-%d %H:%M")
        # Treat as local time, convert to UTC
        local_dt = naive.astimezone()
        return local_dt.astimezone(timezone.utc)
    except ValueError:
        console.print("[red]Could not parse date — skipping.[/red]")
        return None


async def run_scan_events() -> None:
    """Interactive event scan: show each detected meeting request, let CEO add/skip."""
    console.print("[bold blue]Fetching emails and calendar…[/bold blue]")
    gmail = GmailSource()
    calendar = GoogleCalendarSource()

    emails, all_events = await asyncio.gather(
        gmail.fetch_items(max_results=30),
        calendar.fetch_items(days_ahead=7),
    )

    if not emails:
        console.print("No unread emails to scan.")
        return

    email_data = _format_emails_for_action(emails)
    events_text = _format_events_brief(all_events)
    today = date.today().strftime("%A, %B %-d, %Y")

    console.print("[bold blue]Asking Claude to detect meeting requests…[/bold blue]\n")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_SCAN_SYSTEM,
        messages=[{
            "role": "user",
            "content": _SCAN_USER.format(
                today=today,
                events=events_text,
                count=len(emails),
                email_data=email_data,
            ),
        }],
    )

    items = _parse_json_response(response.content[0].text)
    if items is None:
        return

    if not items:
        console.print("[green]No meeting requests found in your inbox.[/green]")
        return

    console.print(f"[bold]{len(items)} meeting request(s) detected.[/bold]\n")
    added = skipped = 0

    for idx, item in enumerate(items, 1):
        from_name = item.get("from_name", "?")
        title = item.get("title", "Meeting")
        quote = item.get("source_quote", "")
        desc = item.get("description", "")
        attendees = item.get("attendees", [])
        duration_min = item.get("duration_minutes", 60)
        is_time_clear = item.get("is_time_clear", False)
        is_reschedule = item.get("is_reschedule", False)
        original_event_title = item.get("original_event_title") or ""

        # Resolve proposed start/end
        start_dt = end_dt = None
        if is_time_clear and item.get("proposed_start_iso"):
            try:
                start_dt = datetime.fromisoformat(item["proposed_start_iso"]).astimezone(timezone.utc)
            except ValueError:
                pass
        if start_dt and item.get("proposed_end_iso"):
            try:
                end_dt = datetime.fromisoformat(item["proposed_end_iso"]).astimezone(timezone.utc)
            except ValueError:
                pass
        if start_dt and not end_dt:
            end_dt = start_dt + timedelta(minutes=duration_min)

        # For reschedule requests: find the existing event on the calendar
        existing_event = None
        if is_reschedule and original_event_title:
            keyword = original_event_title.split()[0] if original_event_title else title.split()[0]
            candidates = calendar.find_events_by_keyword(keyword)
            if candidates:
                existing_event = candidates[0]  # best match from API's relevance ranking

        # Check conflicts if time is known
        conflict_text = ""
        if start_dt and end_dt:
            conflicts = calendar.check_conflicts(start_dt, end_dt)
            # Exclude the event being rescheduled from the conflict list
            if existing_event:
                conflicts = [c for c in conflicts if c.id != existing_event.id]
            if conflicts:
                names = ", ".join(c.title for c in conflicts)
                conflict_text = f"\n[red]⚠ Conflicts:[/red] {names}"
            else:
                conflict_text = "\n[green]✅ No conflicts[/green]"

        time_display = (
            start_dt.astimezone().strftime("%a %b %-d, %-I:%M %p")
            if start_dt else "[yellow]Time not specified[/yellow]"
        )

        # Build panel body
        if is_reschedule:
            panel_type = "[magenta]Reschedule Request[/magenta]"
            if existing_event and existing_event.timestamp:
                old_time = existing_event.timestamp.astimezone().strftime("%a %b %-d, %-I:%M %p")
                reschedule_line = (
                    f"[bold]Old event:[/bold] {existing_event.title}  @  {old_time}\n"
                    f"[bold]New time:[/bold]  {time_display}  ({duration_min} min)\n"
                )
            elif existing_event:
                reschedule_line = (
                    f"[bold]Old event:[/bold] {existing_event.title}  (time unknown)\n"
                    f"[bold]New time:[/bold]  {time_display}  ({duration_min} min)\n"
                )
            else:
                reschedule_line = (
                    f"[bold]Reschedule of:[/bold] {original_event_title or '?'}  [yellow](not found on calendar)[/yellow]\n"
                    f"[bold]New time:[/bold]  {time_display}  ({duration_min} min)\n"
                )
        else:
            panel_type = "[cyan]Meeting Request[/cyan]"
            reschedule_line = (
                f"[bold]Event:[/bold]  {title}\n"
                f"[bold]Time:[/bold]   {time_display}  ({duration_min} min)\n"
            )

        console.print(Panel(
            f"[bold]From:[/bold]   {from_name}\n"
            f"[bold]Quote:[/bold]  [italic]\"{quote}\"[/italic]\n\n"
            + reschedule_line +
            f"[bold]Guests:[/bold] {', '.join(attendees) or '(none)'}\n"
            f"[bold]Notes:[/bold]  {desc}"
            + conflict_text,
            title=f"{panel_type} {idx}/{len(items)}",
            expand=False,
        ))

        # Choose appropriate actions based on context
        if is_reschedule and existing_event:
            choices = ["update", "create-new", "skip"]
            default_choice = "update"
        else:
            choices = ["add", "skip"]
            default_choice = "skip"

        choice = Prompt.ask(
            "[bold]Action[/bold]",
            choices=choices,
            default=default_choice,
        )

        if choice == "skip":
            skipped += 1
            continue

        # If time is unclear, ask now
        if not start_dt:
            start_dt = _prompt_for_datetime(f"Enter start time for '{title}':")
            if not start_dt:
                console.print("[yellow]Skipped (no time entered).[/yellow]")
                skipped += 1
                continue
            end_dt = start_dt + timedelta(minutes=duration_min)

        if choice == "update" and existing_event:
            updated = calendar.update_event(
                event_id=existing_event.id,
                start=start_dt,
                end=end_dt,
            )
            event_link = updated.get("htmlLink", "")
            console.print(f"[green]✓ Event updated[/green]  {event_link}")
            added += 1
        else:
            # "add" or "create-new"
            created = calendar.create_event(
                title=title,
                start=start_dt,
                end=end_dt,
                description=desc,
                attendees=attendees if attendees else None,
            )
            event_link = created.get("htmlLink", "")
            console.print(f"[green]✓ Added to calendar[/green]  {event_link}")
            added += 1

    console.print(f"\n[bold]Done.[/bold]  Added/updated: {added}   Skipped: {skipped}")
