Run the CYVL morning briefing.

Execute: `python main.py briefing`

This fetches unread Gmail and the next 2 days of Google Calendar, then generates a structured briefing with:
- Top 3–5 priorities for the day
- Today's schedule with attendee cross-references
- Tomorrow at a glance
- Inbox triage (Urgent / Needs Reply / FYI / Noise)
- Draft replies for emails that need a response
- Meeting requests detected in email bodies, with conflict checks
- Any scheduling conflicts or flags

Apply all CYVL triage rules from CLAUDE.md: emails from investors, board members, and city officials are always urgent. Cross-reference email senders against today's calendar attendees.
