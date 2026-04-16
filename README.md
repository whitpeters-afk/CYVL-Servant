# CYVL Servant — AI Chief of Staff

An AI-powered executive assistant built with Claude Code that connects Gmail, Google Calendar, and Notion into a unified command center for a startup CEO. Built as a take-home project for CYVL.

## What It Does

CYVL Servant acts as an AI Chief of Staff — it reads across all the CEO's tools, thinks about what matters, and takes action. One dashboard, every morning, everything handled.

**Morning Briefing** — Pulls today's and tomorrow's calendar, cross-references with the inbox, and produces an opinionated daily brief with top priorities, schedule overview, and flags.

**Inbox Triage** — Categorizes emails into Urgent, Needs Reply, FYI, and Noise. Surfaces emails from investors, city officials, and board members automatically. Drafts AI-generated replies the CEO can send, edit, or skip with one click.

**Meeting Detection** — Scans emails for hidden meeting requests ("Can we schedule a call Thursday at 2pm?"), extracts the proposed time, and lets the CEO add it to Google Calendar directly from the dashboard. Handles reschedule requests by updating existing events instead of creating duplicates.

**Notion Task Creation** — Extracts action items from emails and upcoming meetings, assigns priority levels, and creates tasks in a Notion database with one click.

## Demo

https://youtu.be/MnUgz6HwuYA

## Architecture

The system is built as a modular pipeline where each integration is a data source that feeds into a central briefing engine:

```
Gmail (MCP) ──┐
              ├──> Briefing Engine (Claude) ──> Dashboard / CLI
Calendar (MCP)┘                                      │
                                                     ├──> Send Replies (Gmail API)
                                                     ├──> Create Events (Calendar API)
                                                     └──> Create Tasks (Notion API)
```

**Key design decision:** The architecture uses a DataSource base class, so adding new integrations (Slack, HubSpot) means implementing one adapter — the briefing engine and dashboard don't change.

**Models:** The dashboard uses Claude Sonnet for analysis (better accuracy for triage and meeting detection). The CLI briefing also uses Sonnet with streaming output.

## Tech Stack

- **Backend:** Python, Flask
- **AI:** Claude API (Sonnet for analysis, Haiku available for speed)
- **Integrations:** Gmail API, Google Calendar API, Notion API
- **MCP Servers:** Gmail + Google Calendar registered in Claude Code
- **Frontend:** HTML/CSS/JS with CYVL-branded dark theme
- **Infrastructure:** CLAUDE.md for persistent context, slash commands for Claude Code

## Setup

### Prerequisites
- Python 3.10+
- Google Cloud project with Gmail and Calendar APIs enabled
- Notion integration with API key
- Anthropic API key

### Installation

```bash
git clone https://github.com/[your-username]/cyvl-ai-chief-of-staff.git
cd cyvl-ai-chief-of-staff
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Create a `.env` file:

```
ANTHROPIC_API_KEY=your-key
NOTION_API_KEY=your-key
NOTION_TASKS_DB_ID=your-database-id
```

Place your Google OAuth credentials JSON in `credentials/`.

### Running

**Dashboard:**
```bash
source .env && .venv/bin/python main.py serve
```
Open http://localhost:5000

**CLI Commands:**
```bash
python main.py briefing      # Full morning briefing
python main.py replies       # Interactive draft replies
python main.py scan-events   # Detect and add meeting requests
python main.py tasks         # Create Notion tasks from action items
python main.py morning       # Full morning routine (all of the above)
```

## Features in Detail

### Smart Email Triage
- Four-tier classification: Urgent, Needs Reply, FYI, Noise
- CYVL-specific urgency rules: investors, city officials, board members always prioritized
- Cross-references email senders with calendar attendees
- AI-drafted replies that reference calendar context

### Calendar Intelligence
- Detects scheduling requests embedded in email prose
- Handles reschedule requests by updating existing events
- Shows today's and tomorrow's schedule with gap analysis
- Add to Calendar directly from the dashboard

### Notion Integration
- Extracts action items from emails and upcoming meetings
- Assigns priority (Urgent/High/Normal) based on context
- Creates tasks with source attribution and due dates
- CEO reviews and approves before creation

### Error Handling
- Human-in-the-loop: nothing sends or creates without explicit approval
- Graceful degradation if APIs are unreachable
- Token auto-refresh for Google OAuth
- Retry logic on network timeouts

## What I'd Build Next

- **Slack integration** — Daily digest posted to a Slack channel at 7am, slash commands like /briefing from any channel
- **HubSpot CRM sync** — Log meeting notes, update deal stages from email context, sync contact activity
- **Calendar conflict detection** — Flag overlapping events on the dashboard schedule view
- **Notion task inflow** — Pull open/overdue tasks into the morning briefing so nothing falls through the cracks
- **Smart scheduling** — When no time is proposed, suggest 2-3 open calendar slots based on gap analysis
- **Meeting prep** — Auto-generate prep docs by pulling relevant emails, past meetings, and CRM data for each upcoming meeting

## Claude Code Workflow

This project was built entirely using Claude Code with MCP integrations. My process:

1. **Started with architecture** — Gave Claude Code the full project context (CYVL's business, CEO workflows, target features) before writing any code
2. **Built incrementally** — Gmail first, then Calendar, then Notion. Each integration was tested before adding the next
3. **CLAUDE.md as the brain** — Created a persistent context file with CYVL-specific triage rules, priority signals, and tone guidelines
4. **Slash commands** — Set up /briefing, /triage, /replies, /scan-events, /tasks for quick access in Claude Code
5. **Debugging with AI** — Used Claude Code to diagnose API issues, fix edge cases (like reschedule detection), and optimize performance

A big lesson that I learned was that small, specific prompts with one change at a time produce much better results than large multi-part requests.

## Project Structure

```
cyvl-ai-chief-of-staff/
├── CLAUDE.md                    # AI Chief of Staff identity and rules
├── main.py                      # CLI entry point
├── web/
│   ├── app.py                   # Flask backend + API endpoints
│   └── templates/
│       └── index.html           # Dashboard (single-page)
├── sources/
│   ├── base.py                  # DataSource abstract base class
│   ├── gmail.py                 # Gmail integration
│   ├── google_calendar.py       # Calendar integration
│   └── notion.py                # Notion integration
├── briefing/
│   ├── morning_briefing.py      # Briefing engine
│   ├── actions.py               # Reply + scan-events logic
│   └── tasks.py                 # Notion task extraction
├── auth/
│   └── google_oauth.py          # OAuth flow + token management
└── .claude/
    └── commands/                # Slash commands for Claude Code
```
