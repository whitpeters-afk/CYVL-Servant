Triage the current inbox and categorize all unread emails.

Fetch unread emails from Gmail (up to 20) and today's calendar, then categorize every email into exactly one bucket:

**🔴 Urgent** — needs action today
**🟡 Needs Reply** — requires a response within 24–48 hours
**🔵 FYI** — informational, no action needed
**🗑 Promotional / Noise** — can be ignored

For each email, output one line: sender name, subject, and a one-sentence reason for its category.

CYVL triage rules (from CLAUDE.md):
- Investors, board members, city officials → always Urgent
- Emails with "contract," "LOI," "term sheet," "signature," "renewal," "cancel" in subject → always Urgent
- Cross-reference senders against today's calendar — flag with 📅 if the sender is also a meeting attendee today

After categorizing, list any action items or implicit deadlines extracted from the Urgent and Needs Reply emails.
