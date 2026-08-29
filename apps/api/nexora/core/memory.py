"""Organizational memory + Teach NEXORA (ADR-043). Deterministic extraction only."""
import re
from typing import List, Protocol
from packages.core.models import MemoryEntry, MemoryScope, MemoryType

NOUN_CAP = {
    "sheet": "sheets.create", "sheets": "sheets.create", "spreadsheet": "sheets.create",
    "doc": "docs.create", "docs": "docs.create", "document": "docs.create",
    "email": "gmail.send", "emails": "gmail.send", "announcement": "gmail.send",
    "meeting": "calendar.create_event", "meetings": "calendar.create_event",
    "event": "calendar.create_event", "events": "calendar.create_event",
}


class MemoryStore(Protocol):
    async def add(self, entry: MemoryEntry) -> None: ...
    async def all(self) -> List[MemoryEntry]: ...


class InMemoryMemoryStore:
    def __init__(self):
        self._entries: List[MemoryEntry] = []

    async def add(self, entry: MemoryEntry) -> None:
        self._entries.append(entry)

    async def all(self) -> List[MemoryEntry]:
        return list(self._entries)

    def clear(self):
        self._entries.clear()

    def forbiddens(self) -> List[str]:
        return [e.capability for e in self._entries
                if e.effect == "forbid" and e.capability]

    def approval_overrides(self) -> List[str]:
        return [e.capability for e in self._entries
                if e.effect == "require_approval" and e.capability]


class TeachExtractor:
    """Sealed deterministic rule extraction. Unknown sentences become FACTs."""

    def extract(self, instruction: str) -> MemoryEntry:
        text = instruction.lower().strip()

        m = re.search(r"\b(never|forbid|don'?t)\s+(?:create|use|send|schedule)\s+(?:a\s+|an\s+|the\s+)?(\w+)", text)
        if m:
            cap = NOUN_CAP.get(m.group(2)) or NOUN_CAP.get(m.group(2).rstrip("s"))
            if cap:
                return MemoryEntry(type=MemoryType.POLICY, scope=MemoryScope.ORG,
                                   content=instruction, capability=cap, effect="forbid",
                                   provenance="taught")

        if ("approval" in text) and ("always" in text or "require" in text):
            cap = next((NOUN_CAP[w] for w in re.findall(r"[a-z]+", text) if w in NOUN_CAP), None)
            if cap:
                return MemoryEntry(type=MemoryType.POLICY, scope=MemoryScope.ORG,
                                   content=instruction, capability=cap,
                                   effect="require_approval", provenance="taught")

        if text.startswith("prefer"):
            return MemoryEntry(type=MemoryType.PREFERENCE, scope=MemoryScope.ORG,
                               content=instruction, provenance="taught")

        return MemoryEntry(type=MemoryType.FACT, scope=MemoryScope.ORG,
                           content=instruction, provenance="taught")