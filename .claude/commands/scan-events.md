Scan unread emails for meeting requests and add confirmed ones to Google Calendar.

Execute: `python main.py scan-events`

This will:
1. Fetch unread emails and scan every body for scheduling asks — "let's meet," "can we jump on a call," "are you free Thursday," "want to set up time," etc.
2. For each request found, extract:
   - Who is asking and their email
   - The proposed time (if mentioned)
   - The likely meeting topic/title
3. Check the proposed time against the calendar for conflicts
4. Present each detected request for review with a ✅ free or ⚠️ conflicts with [event] status
5. For confirmed requests, create the calendar event with the attendee invited

CYVL scheduling defaults (from CLAUDE.md):
- Investor calls → 60 minutes
- City/partner calls → 45 minutes
- Internal 1:1s → 30 minutes
- Preferred windows: 9–11 AM and 2–4 PM local time
- Flag any slot that creates a back-to-back with no buffer

For reschedule requests, look up the existing event by title keyword before suggesting a new time, and offer to update rather than create a duplicate.
