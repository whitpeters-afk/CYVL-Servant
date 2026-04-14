"""
Notion data source — read tasks and create new tasks in the CEO Tasks database.
"""
import os
from dataclasses import dataclass
from datetime import date

from notion_client import Client

from sources.base import DataSource, SourceItem


@dataclass
class NotionTask:
    """A task to be created in Notion."""
    name: str
    priority: str           # "Urgent" | "High" | "Normal"
    source: str             # "Email" | "Meeting"
    source_detail: str      # sender name / meeting title
    due_date: date | None = None
    url: str = ""


class NotionSource(DataSource):
    """Read and write tasks in the CEO Tasks Notion database."""

    def __init__(self):
        self._client = Client(auth=os.environ["NOTION_API_KEY"])
        self._db_id = os.environ["NOTION_TASKS_DB_ID"]

    @property
    def name(self) -> str:
        return "notion"

    async def fetch_items(self, **kwargs) -> list[SourceItem]:
        """Fetch existing tasks from the Notion database."""
        results = self._client.databases.query(database_id=self._db_id)
        items = []
        for page in results.get("results", []):
            props = page.get("properties", {})
            title_prop = props.get("Name", {}).get("title", [])
            title = title_prop[0]["plain_text"] if title_prop else "(untitled)"
            status_prop = props.get("Status", {}).get("status") or props.get("Status", {}).get("select") or {}
            status = status_prop.get("name", "") if isinstance(status_prop, dict) else ""
            items.append(SourceItem(
                id=page["id"],
                source="notion",
                item_type="task",
                title=title,
                body=status,
                url=page.get("url", ""),
            ))
        return items

    def create_task(self, task: NotionTask) -> str:
        """Create a task in the Notion database. Returns the page URL.

        Only the default "Name" title property is set on the database record so
        this works with any Notion database without requiring specific column
        setup.  All metadata (priority, source, due date, URL) goes into the
        page body as a bulleted list.
        """
        # Build page body with task metadata
        body_lines = [
            f"Priority: {task.priority}",
            f"Source: {task.source} — {task.source_detail}",
        ]
        if task.due_date:
            body_lines.append(f"Due: {task.due_date.isoformat()}")
        if task.url:
            body_lines.append(f"Link: {task.url}")

        children = [
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": line}}]
                },
            }
            for line in body_lines
        ]

        page = self._client.pages.create(
            parent={"database_id": self._db_id},
            properties={
                "Name": {
                    "title": [{"text": {"content": task.name}}]
                }
            },
            children=children,
        )
        return page.get("url", "")
