"""Context Discovery — pre-planning workspace scan (ADR-055).

Before planning, NEXORA scans the user's connected sources (Drive, Gmail, Calendar)
for information related to the goal. The Context Bundle is passed to the compiler
so the plan builds on existing context rather than starting from zero.

The service is lightweight:
- Extracts key entities from the goal (people, projects, dates)
- Runs parallel searches across connected sources
- Aggregates results into a compact bundle
- Never dumps entire documents — uses summaries, metadata, snippets

If discovery fails or finds nothing, the mission proceeds with an empty bundle.
"""
import asyncio
import re
from typing import List

from pydantic import BaseModel


class ContextItem(BaseModel):
    source: str          # "drive" | "gmail" | "calendar" | "web"
    item_type: str       # "file" | "email" | "event"
    title: str
    snippet: str = ""
    resource_id: str = ""
    uri: str = ""
    relevance: str = ""  # brief explanation of why this is relevant


class ContextBundle(BaseModel):
    goal_entities: List[str] = []      # extracted entities from goal
    drive_items: List[ContextItem] = []
    gmail_items: List[ContextItem] = []
    calendar_items: List[ContextItem] = []
    web_items: List[ContextItem] = []  # populated in Phase 4
    summary: str = ""                  # human-readable summary

    def to_human_summary(self) -> str:
        lines = [f"Discovered context for: {', '.join(self.goal_entities) or 'goal'}"]
        if self.drive_items:
            lines.append(f"\nDrive ({len(self.drive_items)} items):")
            lines.extend(f"  • {item.title}" for item in self.drive_items[:5])
        if self.gmail_items:
            lines.append(f"\nGmail ({len(self.gmail_items)} items):")
            lines.extend(f"  • {item.title}" for item in self.gmail_items[:5])
        if self.calendar_items:
            lines.append(f"\nCalendar ({len(self.calendar_items)} items):")
            lines.extend(f"  • {item.title}" for item in self.calendar_items[:5])
        if not any([self.drive_items, self.gmail_items, self.calendar_items]):
            lines.append("\n(No relevant existing context found)")
        return "\n".join(lines)


class ContextDiscoveryService:
    """Pre-planning workspace scan. Fails gracefully to empty bundle."""

    def __init__(self, provider, max_items_per_source: int = 5):
        self.provider = provider
        self.max_items = max_items_per_source

    async def discover(self, goal: str, contract=None) -> ContextBundle:
        """Scan connected sources for relevant context. Never raises."""
        try:
            entities = self._extract_entities(goal)
            drive_items, gmail_items, calendar_items = await asyncio.gather(
                self._search_drive(entities, goal),
                self._search_gmail(entities, goal),
                self._search_calendar(entities, goal),
                return_exceptions=True,
            )

            # Convert exceptions to empty lists
            if isinstance(drive_items, Exception):
                drive_items = []
            if isinstance(gmail_items, Exception):
                gmail_items = []
            if isinstance(calendar_items, Exception):
                calendar_items = []

            bundle = ContextBundle(
                goal_entities=entities,
                drive_items=drive_items,
                gmail_items=gmail_items,
                calendar_items=calendar_items,
                summary=self._build_summary(entities, drive_items, gmail_items, calendar_items),
            )
            return bundle
        except Exception as e:
            # Graceful degradation — empty bundle
            return ContextBundle(summary=f"Context discovery failed: {e}")

        # Common verbs/words that appear capitalized at sentence start but are NOT entities
    STOPWORDS = {
        "the", "and", "for", "with", "this", "that", "these", "those",
        "prepare", "evaluate", "schedule", "create", "investigate", "write",
        "make", "get", "find", "organize", "review", "plan", "launch",
        "analyze", "assess", "draft", "build", "set", "summarize", "research",
        "i", "we", "our", "my", "you", "your", "it", "its",
    }

    def _extract_entities(self, goal: str) -> List[str]:
        """Extract key entities from the goal (simple heuristic extraction)."""
        text = goal.lower()
        quoted = re.findall(r'"([^"]+)"', goal)
        caps = re.findall(r'\b[A-Z][a-z]+\b', goal)
        emails = re.findall(r'\b[\w.-]+@[\w.-]+\.\w+\b', text)
        dates = re.findall(r'\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b', text)

        entities = []
        entities.extend(quoted)
        entities.extend([c for c in caps if len(c) > 3 and c.lower() not in self.STOPWORDS])
        entities.extend(emails)
        entities.extend(dates)
        seen = set()
        return [e for e in entities if not (e.lower() in seen or seen.add(e.lower()))]
    
    async def _search_drive(self, entities: List[str], goal: str) -> List[ContextItem]:
        """Search Drive for relevant files."""
        if not hasattr(self.provider, "search_files"):
            return []

        query = self._build_query(entities, goal)
        results = await self.provider.search_files(query)
        items = []
        for r in results[:self.max_items]:
            items.append(ContextItem(
                source="drive",
                item_type="file",
                title=r.get("name", "Untitled"),
                snippet=r.get("type", ""),
                resource_id=r.get("id", ""),
                uri=f"drive://{r.get('id', '')}",
                relevance="Matches goal keywords",
            ))
        return items

    async def _search_gmail(self, entities: List[str], goal: str) -> List[ContextItem]:
        """Search Gmail for relevant emails."""
        if not hasattr(self.provider, "search_emails"):
            return []

        query = self._build_query(entities, goal)
        results = await self.provider.search_emails(query, self.max_items)
        items = []
        for r in results[:self.max_items]:
            items.append(ContextItem(
                source="gmail",
                item_type="email",
                title=r.get("subject", "No subject"),
                snippet=r.get("snippet", "")[:100],
                resource_id=r.get("id", ""),
                uri=f"gmail://{r.get('id', '')}",
                relevance="Matches goal keywords",
            ))
        return items

    async def _search_calendar(self, entities: List[str], goal: str) -> List[ContextItem]:
        """Search Calendar for relevant events."""
        if not hasattr(self.provider, "search_events"):
            return []

        # Calendar search is less common; skip if not available
        try:
            query = self._build_query(entities, goal)
            results = await self.provider.search_events(query)
            items = []
            for r in results[:self.max_items]:
                items.append(ContextItem(
                    source="calendar",
                    item_type="event",
                    title=r.get("summary", "Untitled event"),
                    snippet=r.get("description", "")[:100],
                    resource_id=r.get("id", ""),
                    uri=r.get("htmlLink", f"calendar://{r.get('id', '')}"),
                    relevance="Matches goal keywords",
                ))
            return items
        except Exception:
            return []

    def _build_query(self, entities: List[str], goal: str) -> str:
        """Build a search query from entities and goal."""
        # Use the first 3 entities + first 50 chars of goal
        parts = entities[:3]
        if len(goal) > 50:
            parts.append(goal[:50])
        else:
            parts.append(goal)
        return " ".join(parts)

    def _build_summary(self, entities, drive, gmail, calendar) -> str:
        """Build a human-readable summary of discovered context."""
        found = []
        if drive:
            found.append(f"{len(drive)} Drive file(s)")
        if gmail:
            found.append(f"{len(gmail)} Gmail message(s)")
        if calendar:
            found.append(f"{len(calendar)} Calendar event(s)")

        if not found:
            return "No relevant existing context found."

        parts = []
        if entities:
            parts.append(f"Goal entities: {', '.join(entities[:5])}")
        parts.append("Found " + ", ".join(found))
        return ". ".join(parts)