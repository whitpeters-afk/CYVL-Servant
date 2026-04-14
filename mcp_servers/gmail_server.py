"""
MCP server — Gmail tools.

Exposes Gmail capabilities as MCP tools so Claude can call them directly.

Run as a subprocess (stdio transport):
    python -m mcp_servers.gmail_server
"""
import asyncio
import json

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from sources.gmail import GmailSource

server = Server("gmail")
_gmail: GmailSource | None = None


def _get_gmail() -> GmailSource:
    global _gmail
    if _gmail is None:
        _gmail = GmailSource()
    return _gmail


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="gmail_list_unread",
            description="List unread emails in the inbox. Returns subject, sender, snippet, and ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "default": 20, "description": "Maximum number of emails to return"},
                    "query": {"type": "string", "default": "is:inbox is:unread", "description": "Gmail search query"},
                },
            },
        ),
        types.Tool(
            name="gmail_get_email",
            description="Get the full body and metadata of a specific email by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "email_id": {"type": "string", "description": "Gmail message ID"},
                },
                "required": ["email_id"],
            },
        ),
        types.Tool(
            name="gmail_send",
            description="Send an email on behalf of the user.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "reply_to_msg_id": {"type": "string", "description": "Message-ID to thread the reply to (optional)"},
                },
                "required": ["to", "subject", "body"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    gmail = _get_gmail()

    if name == "gmail_list_unread":
        items = await gmail.fetch_items(
            max_results=arguments.get("max_results", 20),
            query=arguments.get("query", "is:inbox is:unread"),
        )
        result = [
            {
                "id": item.id,
                "subject": item.title,
                "from": item.participants[0] if item.participants else "",
                "timestamp": item.timestamp.isoformat() if item.timestamp else None,
                "priority": item.priority,
                "labels": item.labels,
                "snippet": item.body[:300],
                "url": item.url,
            }
            for item in items
        ]
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "gmail_get_email":
        email_id = arguments["email_id"]
        # Fetch the specific message
        items = await gmail.fetch_items(query=f"rfc822msgid:{email_id}", max_results=1)
        if not items:
            # Fall back to direct ID fetch
            import asyncio
            msg = gmail._service.users().messages().get(
                userId="me", id=email_id, format="full"
            ).execute()
            item = gmail._to_source_item(msg)
        else:
            item = items[0]

        result = {
            "id": item.id,
            "subject": item.title,
            "participants": item.participants,
            "timestamp": item.timestamp.isoformat() if item.timestamp else None,
            "body": item.body,
            "labels": item.labels,
            "url": item.url,
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "gmail_send":
        sent = gmail.send_message(
            to=arguments["to"],
            subject=arguments["subject"],
            body=arguments["body"],
            reply_to_msg_id=arguments.get("reply_to_msg_id"),
        )
        return [types.TextContent(type="text", text=json.dumps({"sent_id": sent.get("id"), "status": "sent"}))]

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
