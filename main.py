"""
AI Chief of Staff — entry point.

Usage:
    python main.py briefing        # Generate morning briefing
    python main.py replies         # Review and send AI-drafted email replies
    python main.py scan-events     # Review and add detected meeting requests to calendar
    python main.py serve           # Start the web dashboard (http://localhost:5000)
    python main.py auth            # Run Google OAuth flow
    python main.py tasks           # Extract action items and push to Notion
"""
import asyncio
import sys

from dotenv import load_dotenv
load_dotenv()


def run_morning_briefing():
    from briefing.morning_briefing import run_and_print
    asyncio.run(run_and_print())


def run_replies():
    from briefing.actions import run_replies as _run
    asyncio.run(_run())


def run_triage():
    from briefing.triage import run_triage as _run
    asyncio.run(_run())


def run_scan_events():
    from briefing.actions import run_scan_events as _run
    asyncio.run(_run())


def run_serve():
    from web.app import app
    port = int(__import__("os").environ.get("PORT", 5000))
    print(f"CYVL Servant running at http://localhost:{port}")
    app.run(debug=False, port=port)


def run_tasks():
    from briefing.tasks import run_tasks as _run
    asyncio.run(_run())


def run_auth():
    from auth.google_auth import main as auth_main
    auth_main()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "briefing"
    if cmd == "auth":
        run_auth()
    elif cmd == "briefing":
        run_morning_briefing()
    elif cmd == "triage":
        run_triage()
    elif cmd == "replies":
        run_replies()
    elif cmd == "scan-events":
        run_scan_events()
    elif cmd == "serve":
        run_serve()
    elif cmd == "tasks":
        run_tasks()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python main.py [auth|briefing|triage|replies|scan-events|serve|tasks]")
        sys.exit(1)


if __name__ == "__main__":
    main()
