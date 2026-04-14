"""
/tasks command — extract action items from inbox + calendar and push to Notion.

    python main.py tasks
"""
import asyncio
import json
import os
from datetime import date, timedelta

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from sources.gmail import GmailSource
from sources.google_calendar import GoogleCalendarSource
from sources.notion import NotionSource, NotionTask

console = Console()

_TASKS_SYSTEM = """\
You are an AI Chief of Staff for a startup CEO.
Your job is to read emails and calendar events and extract concrete action items that belong in a task manager.

Rules:
- Only surface real tasks — explicit asks, firm commitments, deadlines, follow-ups.
- Do NOT create tasks for passive reading, FYIs, or noise.
- Each task must be specific and actionable (start with a verb: "Reply to...", "Send...", "Review...", "Schedule...", "Follow up on...").
- Prefer tasks with clear owners / sources so the CEO knows the context at a glance.

Return a JSON array ONLY — no prose, no markdown fences.

Each item:
{
  "name": "<specific actionable task — start with a verb>",
  "priority": "Urgent" | "High" | "Normal",
  "source": "Email" | "Meeting",
  "source_detail": "<sender name and company — OR — meeting title and attendees>",
  "due_date": "<YYYY-MM-DD or null>",
  "url": "<direct link to the email/event if available, or null>",
  "reason": "<one sentence: why this is a task>"
}

Priority guide:
- Urgent: investor/board/city official asks, contract/LOI/deadline items, things needed today
- High: replies needed within 24h, important follow-ups, team blockers
- Normal: everything else actionable
"""

_TASKS_USER = """\
Today is {today}.

## Unread Emails ({email_count} emails)
{email_data}

## Today's Calendar ({today_event_count} events)
{today_event_data}

## Tomorrow's Calendar ({tomorrow_event_count} events)
{tomorrow_event_data}

Extract every concrete action item. For tomorrow's meetings, create a prep task (e.g. "Prepare talking points for <meeting> tomorrow at <time>") if the meeting warrants preparation. Return a JSON array only."""


def _format_emails(emails) -> str:
    lines = []
    for e in emails:
        sender = e.participants[0] if e.participants else "unknown"
        ts = e.timestamp.astimezone().strftime("%b %-d %-I:%M %p") if e.timestamp else ""
        body = e.body[:600].replace("\n", " ").strip()
        url = e.url or ""
        lines.append(
            f"[{e.id}] {e.title}\n"
            f"  From: {sender} | {ts} | Priority: {e.priority}\n"
            f"  URL: {url}\n"
            f"  {body}"
        )
    return "\n\n".join(lines)


def _format_events(events) -> str:
    if not events:
        return "(none)"
    lines = []
    for e in events:
        if e.timestamp:
            ts = e.timestamp.astimezone().strftime("%-I:%M %p")
        else:
            ts = "All day"
        attendees = ", ".join(e.participants[:4]) if e.participants else "no attendees"
        lines.append(f"[{e.id}] {ts}: {e.title} — {attendees}")
    return "\n".join(lines)


def _priority_color(priority: str) -> str:
    return {"Urgent": "red", "High": "yellow", "Normal": "green"}.get(priority, "white")


async def run_tasks() -> None:
    """Fetch inbox + calendar, extract tasks, prompt for approval, push to Notion."""
    console.print("[bold blue]Fetching emails and calendar…[/bold blue]")
    gmail = GmailSource()
    calendar = GoogleCalendarSource()

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

    if not emails and not today_events and not tomorrow_events:
        console.print("Nothing to extract tasks from.")
        return

    email_data = _format_emails(emails)
    today_event_data = _format_events(today_events)
    tomorrow_event_data = _format_events(tomorrow_events)

    console.print("[bold blue]Asking Claude to extract action items…[/bold blue]\n")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_TASKS_SYSTEM,
        messages=[{
            "role": "user",
            "content": _TASKS_USER.format(
                today=today.strftime("%A, %B %-d, %Y"),
                email_count=len(emails),
                email_data=email_data,
                today_event_count=len(today_events),
                today_event_data=today_event_data,
                tomorrow_event_count=len(tomorrow_events),
                tomorrow_event_data=tomorrow_event_data,
            ),
        }],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Could not parse Claude response ({exc}):[/red]\n{raw}")
        return

    if not items:
        console.print("[green]No action items found.[/green]")
        return

    # ── Preview table ─────────────────────────────────────────────────────────
    table = Table(title=f"Proposed Tasks ({len(items)})", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Task", min_width=30)
    table.add_column("Priority", width=8)
    table.add_column("Source", width=7)
    table.add_column("From / Meeting", min_width=20)
    table.add_column("Due", width=12)

    for i, item in enumerate(items, 1):
        priority = item.get("priority", "Normal")
        color = _priority_color(priority)
        due = item.get("due_date") or "—"
        table.add_row(
            str(i),
            item.get("name", "?"),
            f"[{color}]{priority}[/{color}]",
            item.get("source", "?"),
            item.get("source_detail", "?"),
            due,
        )

    console.print(table)
    console.print()

    # ── Approval flow ─────────────────────────────────────────────────────────
    bulk = Prompt.ask(
        "[bold]Create all tasks, review one-by-one, or cancel?[/bold]",
        choices=["all", "review", "cancel"],
        default="review",
    )

    if bulk == "cancel":
        console.print("[yellow]Cancelled.[/yellow]")
        return

    notion = NotionSource()
    created = skipped = 0

    if bulk == "all":
        to_create = items
    else:
        to_create = []
        for i, item in enumerate(items, 1):
            priority = item.get("priority", "Normal")
            color = _priority_color(priority)
            console.print(Panel(
                f"[bold]Task:[/bold]    {item.get('name', '?')}\n"
                f"[bold]Priority:[/bold] [{color}]{priority}[/{color}]\n"
                f"[bold]Source:[/bold]  {item.get('source', '?')} — {item.get('source_detail', '?')}\n"
                f"[bold]Due:[/bold]     {item.get('due_date') or '(none)'}\n"
                f"[bold]Why:[/bold]     {item.get('reason', '')}",
                title=f"[cyan]Task {i}/{len(items)}[/cyan]",
                expand=False,
            ))
            choice = Prompt.ask("[bold]Add to Notion?[/bold]", choices=["yes", "no"], default="yes")
            if choice == "yes":
                to_create.append(item)
            else:
                skipped += 1

    # ── Create in Notion ──────────────────────────────────────────────────────
    for item in to_create:
        due_date = None
        if item.get("due_date"):
            try:
                due_date = date.fromisoformat(item["due_date"])
            except ValueError:
                pass

        task = NotionTask(
            name=item.get("name", "Untitled task"),
            priority=item.get("priority", "Normal"),
            source=item.get("source", "Email"),
            source_detail=item.get("source_detail", ""),
            due_date=due_date,
            url=item.get("url") or "",
        )
        try:
            page_url = notion.create_task(task)
            console.print(f"[green]✓[/green] {task.name}  [dim]{page_url}[/dim]")
            created += 1
        except Exception as exc:
            console.print(f"[red]✗ Failed to create '{task.name}': {exc}[/red]")

    console.print(f"\n[bold]Done.[/bold]  Created: {created}   Skipped: {skipped}")
