"""
Flask web dashboard — CYVL Servant.

Run from the project root:
    python -m web.app
    # or
    flask --app web.app run --port 5000
"""
import asyncio
import json
import os
import sys
import time
from datetime import date, datetime, timezone, timedelta
from email.utils import parseaddr
from pathlib import Path

# Ensure project root is on sys.path when run directly
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import traceback

import anthropic
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

from sources.gmail import GmailSource
from sources.google_calendar import GoogleCalendarSource

app = Flask(__name__, template_folder="templates")
app.debug = True


# ── Structured briefing prompt ─────────────────────────────────────────────────

_DASHBOARD_SYSTEM = """\
You are an AI Chief of Staff. Return a single JSON object ONLY — no prose, no markdown fences.

Required keys:

{
  "top_priorities": [{"text": "<actionable — name people, deadlines, amounts>", "urgency": "high|medium|low"}],
  "today_schedule": [{"time": "<9:00 AM>", "title": "<title>", "attendees": ["<email>"], "attendee_has_email": false}],
  "tomorrow_schedule": [{"time": "<2:00 PM>", "title": "<title>", "note": "<optional>"}],
  "flags": ["<conflicts, overdue items, payment requests>"],
  "inbox": [{"email_id": "<id>", "from_name": "<name>", "from_email": "<addr>", "subject": "<subject>", "snippet": "<1 sentence>", "category": "urgent|needs_reply|fyi|promotional", "reason": "<one sentence>", "draft_reply": "<ready-to-send reply, or null>"}],
  "meeting_requests": [{"email_id": "<id>", "from_name": "<name>", "source_quote": "<exact ask>", "title": "<title>", "description": "<1-2 sentences>", "proposed_start_iso": "<ISO 8601 or null>", "proposed_end_iso": "<ISO 8601 or null>", "duration_minutes": 60, "attendees": ["<email>"], "is_time_clear": true, "is_reschedule": false, "original_event_title": "<null or existing event name>"}]
}

Rules:
- top_priorities: 3–5 bullets, specific and actionable.
- today_schedule: attendee_has_email=true if that attendee also sent an unread email.
- flags: [] if nothing to flag.
- inbox: every email in exactly one category; draft_reply only for urgent/needs_reply.
- meeting_requests: is_reschedule=true for reschedule/move asks; [] if none found."""

_DASHBOARD_USER = """\
Today is {today}. Tomorrow is {tomorrow}.

## Today's Calendar ({today_count} events)
{today_events}

## Tomorrow's Calendar ({tomorrow_count} events)
{tomorrow_events}

## Today's Attendee Emails (cross-reference these against the inbox)
{attendees}

## Unread Emails ({email_count} emails)
{email_data}

Analyze everything and return the JSON dashboard object."""


# ── Data fetching ──────────────────────────────────────────────────────────────

async def _fetch_raw_data() -> dict:
    """Phase 1: fast fetch from Gmail + Calendar APIs — no Claude call."""
    t0 = time.perf_counter()
    print(f"[/api/data] start", flush=True)

    try:
        gmail = GmailSource()
        calendar = GoogleCalendarSource()
    except Exception as exc:
        raise RuntimeError(f"Failed to initialize Google API clients: {exc}") from exc

    try:
        print(f"[/api/data] Gmail fetch start  t={time.perf_counter()-t0:.2f}s", flush=True)
        emails = await gmail.fetch_items(max_results=20, metadata_only=True)
        print(f"[/api/data] Gmail done ({len(emails)} emails)  t={time.perf_counter()-t0:.2f}s", flush=True)
        all_events = await calendar.fetch_items(days_ahead=2)
        print(f"[/api/data] Calendar done ({len(all_events)} events)  t={time.perf_counter()-t0:.2f}s", flush=True)
    except Exception as exc:
        raise RuntimeError(f"Could not reach Gmail or Google Calendar: {exc}") from exc

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

    # Collect sender addresses so we can flag attendee_has_email immediately
    email_sender_addrs: set[str] = set()
    for e in emails:
        if e.participants:
            _, addr = parseaddr(e.participants[0])
            if addr:
                email_sender_addrs.add(addr.lower())

    def fmt_event(ev) -> dict:
        if ev.timestamp:
            if ev.timestamp.hour == 0 and ev.timestamp.minute == 0:
                ts = "All day"
            else:
                ts = ev.timestamp.astimezone().strftime("%-I:%M %p")
        else:
            ts = "All day"
        attendees = ev.participants[:4]
        attendee_has_email = any(
            parseaddr(a)[1].lower() in email_sender_addrs for a in attendees
        )
        return {"time": ts, "title": ev.title, "attendees": attendees,
                "attendee_has_email": attendee_has_email}

    def fmt_email(e) -> dict:
        from_raw = e.participants[0] if e.participants else ""
        from_name, from_addr = parseaddr(from_raw)
        if not from_name:
            from_name = from_addr or "Unknown"
        return {
            "id": e.id,
            "from_name": from_name,
            "from_email": from_addr or from_raw,
            "subject": e.title,
            "snippet": e.body[:200].replace("\n", " ").strip(),
            "thread_id": e.raw.get("threadId", ""),
        }

    result = {
        "date": today.strftime("%A, %B %-d, %Y"),
        "today_schedule": [fmt_event(e) for e in today_events],
        "tomorrow_schedule": [fmt_event(e) for e in tomorrow_events],
        "emails": [fmt_email(e) for e in emails],
        "inbox_zero": len(emails) == 0,
        "_email_thread_map": {e.id: e.raw.get("threadId") for e in emails},
    }
    print(f"[/api/data] done  total={time.perf_counter()-t0:.2f}s", flush=True)
    return result


def _fmt_schedule(schedule: list[dict]) -> str:
    """Format a list of raw schedule dicts (from /api/data) into a prompt string."""
    if not schedule:
        return "(none)"
    return "\n".join(
        "- {time}: **{title}** — {attendees}".format(
            time=e["time"],
            title=e["title"],
            attendees=", ".join(e.get("attendees", [])[:4]) or "no attendees",
        )
        for e in schedule
    )


def _fmt_emails(emails: list[dict], attendee_addrs: set[str]) -> str:
    """Format raw email dicts (from /api/data) into a prompt string."""
    if not emails:
        return "(no unread emails)"
    lines = []
    for e in emails:
        flag = " 📅" if e.get("from_email", "").lower() in attendee_addrs else ""
        lines.append(
            f"**[{e['id']}] {e['subject']}**{flag}\n"
            f"  From: {e['from_name']} <{e['from_email']}>\n"
            f"  {e.get('snippet', '')}"
        )
    return "\n\n".join(lines)


async def _analyze_data(raw_data: dict) -> dict:
    """Phase 2: build prompt from already-fetched raw_data and call Claude.

    raw_data is the payload from /api/data — no re-fetching of Gmail or Calendar.
    """
    t0 = time.perf_counter()
    print(f"[/api/analyze] start (using pre-fetched data, no re-fetch)", flush=True)

    today = date.today()
    tomorrow = today + timedelta(days=1)

    today_schedule: list[dict] = raw_data.get("today_schedule", [])
    tomorrow_schedule: list[dict] = raw_data.get("tomorrow_schedule", [])
    emails: list[dict] = raw_data.get("emails", [])

    # Flat set of attendee email addresses from today's calendar
    attendee_addrs: set[str] = {
        addr.lower()
        for ev in today_schedule
        for addr in ev.get("attendees", [])
    }

    prompt = _DASHBOARD_USER.format(
        today=today.strftime("%A, %B %-d, %Y"),
        tomorrow=tomorrow.strftime("%A, %B %-d, %Y"),
        today_count=len(today_schedule),
        today_events=_fmt_schedule(today_schedule),
        tomorrow_count=len(tomorrow_schedule),
        tomorrow_events=_fmt_schedule(tomorrow_schedule),
        attendees=", ".join(sorted(attendee_addrs)) or "(none)",
        email_count=len(emails),
        email_data=_fmt_emails(emails, attendee_addrs),
    )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    _MODEL = "claude-haiku-4-5-20251001"
    _prompt_chars = len(_DASHBOARD_SYSTEM) + len(prompt)
    # Rough token estimate: ~4 chars per token
    _approx_tokens = _prompt_chars // 4
    print(f"[/api/analyze] model={_MODEL}  prompt≈{_approx_tokens:,} tokens  ({_prompt_chars:,} chars)  t={time.perf_counter()-t0:.2f}s", flush=True)

    def _call_claude() -> str:
        t_claude = time.perf_counter()
        print(f"[/api/analyze] Claude API call start  t={time.perf_counter()-t0:.2f}s", flush=True)
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=8192,
            system=[{
                "type": "text",
                "text": _DASHBOARD_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )
        print(f"[/api/analyze] Claude API call done   t={time.perf_counter()-t0:.2f}s  ({time.perf_counter()-t_claude:.2f}s)  input_tokens={resp.usage.input_tokens}  output_tokens={resp.usage.output_tokens}", flush=True)
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return raw

    def _parse_json(raw: str) -> dict:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            print("JSON parse failed on first attempt, retrying Claude call...")
            traceback.print_exc()
            raw2 = _call_claude()
            return json.loads(raw2)

    try:
        data = _parse_json(_call_claude())
    except json.JSONDecodeError:
        print("JSON parse failed on retry — returning error state")
        traceback.print_exc()
        return {
            "top_priorities": [],
            "flags": ["AI analysis unavailable — JSON parse error."],
            "inbox": [],
            "meeting_requests": [],
            "_email_thread_map": raw_data.get("_email_thread_map", {}),
            "_parse_error": True,
        }

    # Enrich meeting requests with live conflict + existing-event data.
    # Calendar is only instantiated here if there are meeting requests to check.
    meeting_requests = data.get("meeting_requests", [])
    if meeting_requests:
        try:
            calendar = GoogleCalendarSource()
        except Exception:
            calendar = None

        for req in meeting_requests:
            req["conflict_info"] = None
            req["existing_event_id"] = None
            req["existing_event_time"] = None

            if not calendar:
                continue

            start_iso = req.get("proposed_start_iso")
            end_iso = req.get("proposed_end_iso")

            if start_iso and req.get("is_time_clear"):
                try:
                    start_dt = datetime.fromisoformat(start_iso).astimezone(timezone.utc)
                    dur = req.get("duration_minutes", 60)
                    end_dt = (
                        datetime.fromisoformat(end_iso).astimezone(timezone.utc)
                        if end_iso else start_dt + timedelta(minutes=dur)
                    )
                    conflicts = calendar.check_conflicts(start_dt, end_dt)

                    if req.get("is_reschedule") and req.get("original_event_title"):
                        keyword = (req["original_event_title"] or "").split()[0]
                        candidates = calendar.find_events_by_keyword(keyword)
                        if candidates:
                            existing = candidates[0]
                            req["existing_event_id"] = existing.id
                            req["existing_event_time"] = (
                                existing.timestamp.astimezone().strftime("%a %b %-d, %-I:%M %p")
                                if existing.timestamp else None
                            )
                            conflicts = [c for c in conflicts if c.id != existing.id]

                    if conflicts:
                        req["conflict_info"] = {"has_conflict": True, "names": [c.title for c in conflicts]}
                    else:
                        req["conflict_info"] = {"has_conflict": False}
                except (ValueError, KeyError):
                    pass

    result = {
        **data,
        "inbox_zero": len(emails) == 0,
        "_email_thread_map": raw_data.get("_email_thread_map", {}),
    }
    print(f"[/api/analyze] done  total={time.perf_counter()-t0:.2f}s", flush=True)
    return result


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def get_data():
    """Phase 1: returns raw emails + calendar events immediately, no AI."""
    try:
        data = asyncio.run(_fetch_raw_data())
        return jsonify({"ok": True, "data": data})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/analyze", methods=["POST"])
def get_analysis():
    """Phase 2: runs Claude triage, priorities, drafts, meeting detection.

    Expects a JSON body containing the raw data already fetched by /api/data.
    No Gmail or Calendar re-fetch happens here.
    """
    raw_data = request.get_json(force=True) or {}
    try:
        data = asyncio.run(_analyze_data(raw_data))
        return jsonify({"ok": True, "data": data})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/send-reply", methods=["POST"])
def send_reply():
    body = request.json
    try:
        gmail = GmailSource()
        gmail.send_message(
            to=body["to"],
            subject=body["subject"],
            body=body["body"],
            reply_to_msg_id=body.get("email_id") or None,
            thread_id=body.get("thread_id") or None,
        )
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/add-event", methods=["POST"])
def add_event():
    body = request.json
    try:
        calendar = GoogleCalendarSource()
        start = datetime.fromisoformat(body["start_iso"]).astimezone(timezone.utc)
        end_iso = body.get("end_iso")
        dur = body.get("duration_minutes", 60)
        end = (
            datetime.fromisoformat(end_iso).astimezone(timezone.utc)
            if end_iso else start + timedelta(minutes=dur)
        )
        created = calendar.create_event(
            title=body["title"],
            start=start,
            end=end,
            description=body.get("description", ""),
            attendees=body.get("attendees") or None,
        )
        return jsonify({"ok": True, "link": created.get("htmlLink", "")})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/update-event", methods=["POST"])
def update_event():
    body = request.json
    try:
        calendar = GoogleCalendarSource()
        start = datetime.fromisoformat(body["start_iso"]).astimezone(timezone.utc)
        end_iso = body.get("end_iso")
        dur = body.get("duration_minutes", 60)
        end = (
            datetime.fromisoformat(end_iso).astimezone(timezone.utc)
            if end_iso else start + timedelta(minutes=dur)
        )
        updated = calendar.update_event(
            event_id=body["event_id"],
            start=start,
            end=end,
        )
        return jsonify({"ok": True, "link": updated.get("htmlLink", "")})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)
