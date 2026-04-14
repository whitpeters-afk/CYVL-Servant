Run the full CYVL CEO morning routine.

Execute: `python main.py morning`

This runs all four morning flows in sequence, prompting before each step:

1. **Briefing** — fetches unread Gmail and the next 2 days of Google Calendar, then generates:
   - Top 3–5 priorities for the day
   - Today's schedule with attendee cross-references
   - Tomorrow at a glance
   - Inbox triage (Urgent / Needs Reply / FYI / Noise)
   - Draft replies for emails that need a response
   - Meeting requests detected in email bodies, with conflict checks
   - Any scheduling conflicts or flags

2. **Replies** *(prompted)* — reviews AI-drafted replies and sends approved ones via Gmail

3. **Meeting requests** *(prompted)* — scans emails for scheduling asks and adds confirmed ones to Google Calendar

4. **Notion tasks** *(prompted)* — extracts action items from inbox + calendar and pushes them to Notion

Apply all CYVL triage rules from CLAUDE.md: emails from investors, board members, and city officials are always urgent. Cross-reference email senders against today's calendar attendees.
