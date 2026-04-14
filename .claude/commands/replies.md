Show AI-drafted replies for emails that need a response, then offer to send them.

Execute: `python main.py replies`

This will:
1. Fetch unread emails and identify those in the Urgent and Needs Reply categories
2. Generate a ready-to-send draft reply for each one
3. Present each draft for review
4. Ask which replies to send, then send them via Gmail

Draft reply guidelines (from CLAUDE.md):
- Lead with the answer or decision — no filler openers
- 3–6 sentences unless clearly more is needed
- **City officials**: slightly more formal, address them by title and city name
- **Investors**: confident and data-forward, reference metrics or milestones when relevant
- **Board members**: direct, no hedging
- **Team members**: clear and decisive

For each draft, show:
- **To**: sender name and email
- **Re**: subject line
- **Draft**: the ready-to-send reply text
- Option to send as-is, edit, or skip
