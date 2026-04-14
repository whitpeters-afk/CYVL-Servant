Extract action items from inbox and calendar, then push approved tasks to Notion.

Execute: `python main.py tasks`

This will:
1. Fetch unread emails (up to 30) and the next 2 days of calendar events
2. Ask Claude to extract concrete, actionable tasks — explicit asks, firm commitments, deadlines, follow-ups
3. Display a preview table with task name, priority, source, and due date
4. Prompt to create all at once, review one-by-one, or cancel
5. Push approved tasks to the Notion task database

Task extraction rules:
- Only surface real tasks — explicit asks, firm commitments, deadlines, follow-ups
- No tasks for passive FYIs or noise
- Each task starts with a verb: "Reply to…", "Send…", "Review…", "Schedule…", "Follow up on…"

Priority levels:
- **Urgent**: investor/board/city official asks, contract/LOI/deadline items, things needed today
- **High**: replies needed within 24h, important follow-ups, team blockers
- **Normal**: everything else actionable

For tomorrow's meetings, prep tasks are auto-generated (e.g. "Prepare talking points for <meeting> tomorrow at <time>") when the meeting warrants preparation.
