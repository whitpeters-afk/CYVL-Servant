"""
MCP server — Google Calendar tools.

Exposes Calendar capabilities as MCP tools so Claude can call them directly.

Run as a subprocess (stdio transport):
    python -m mcp_servers.calendar_server
"""
import asyncio
import json
from datetime import datetime, timezone, timedelta

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from sources.google_calendar import GoogleCalendarSource

server = Server("google_calendar")
_cal: GoogleCalendarSource | None = None


def _get_cal() -> GoogleCalendarSource:
    global _cal
    if _cal is None:
        _cal = GoogleCalendarSource()
    return _cal


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="calendar_list_events",
            description="List upcoming calendar events. Defaults to today's events.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "default": 1, "description": "Number of days ahead to fetch (0 = today only)"},
                    "max_results": {"type": "integer", "default": 20},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
            },
        ),
        types.Tool(
            name="calendar_check_conflicts",
            description="Check for scheduling conflicts in a proposed time window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_iso": {"type": "string", "description": "Proposed start time in ISO 8601 format (with timezone)"},
                    "end_iso": {"type": "string", "description": "Proposed end time in ISO 8601 format (with timezone)"},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
                "required": ["start_iso", "end_iso"],
            },
        ),
        types.Tool(
            name="calendar_todays_attendees",
            description="Return the email addresses of all attendees in today's calendar events.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    cal = _get_cal()

    if name == "calendar_list_events":
        items = await cal.fetch_items(
            days_ahead=arguments.get("days_ahead", 1),
            max_results=arguments.get("max_results", 20),
            calendar_id=arguments.get("calendar_id", "primary"),
        )
        result = [
            {
                "id": item.id,
                "title": item.title,
                "start": item.timestamp.isoformat() if item.timestamp else None,
                "attendees": item.participants,
                "description": item.body[:500],
                "status": item.labels[0] if item.labels else "confirmed",
                "url": item.url,
            }
            for item in items
        ]
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "calendar_check_conflicts":
        start = datetime.fromisoformat(arguments["start_iso"]).astimezone(timezone.utc)
        end = datetime.fromisoformat(arguments["end_iso"]).astimezone(timezone.utc)
        conflicts = cal.check_conflicts(start, end, arguments.get("calendar_id", "primary"))
        result = {
            "has_conflicts": len(conflicts) > 0,
            "conflicts": [
                {
                    "id": item.id,
                    "title": item.title,
                    "start": item.timestamp.isoformat() if item.timestamp else None,
                    "url": item.url,
                }
                for item in conflicts
            ],
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "calendar_todays_attendees":
        emails = cal.get_todays_attendee_emails()
        return [types.TextContent(type="text", text=json.dumps({"attendee_emails": sorted(emails)}))]

    raise ValueError(f"Unknown tool: {name}")


async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
