"""
Abstract DataSource interface.

Every data source (Gmail, Calendar, Notion, HubSpot, Slack, …) implements
this interface so the briefing engine can treat them uniformly.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SourceItem:
    """
    Normalized representation of any item from any data source.

    Each source maps its native objects (emails, events, tasks, deals, …)
    onto this common schema.  `raw` carries the original payload for any
    fields not covered here.
    """
    id: str
    source: str                        # e.g. "gmail", "google_calendar"
    item_type: str                     # e.g. "email", "event", "task"
    title: str
    body: str = ""
    timestamp: datetime | None = None
    participants: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    priority: str = "normal"           # "urgent" | "high" | "normal" | "low"
    url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class DataSource(ABC):
    """Base class for all data source adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable source identifier, e.g. 'gmail'."""

    @abstractmethod
    async def fetch_items(self, **kwargs) -> list[SourceItem]:
        """
        Fetch items from this source.

        kwargs are source-specific filters (e.g. max_results, date_range).
        Returns a list of normalized SourceItems.
        """

    async def health_check(self) -> bool:
        """Return True if the source is reachable and authenticated."""
        try:
            await self.fetch_items(max_results=1)
            return True
        except Exception:
            return False
