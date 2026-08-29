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
    """Organizational memory with semantic (vector) retrieval (ADR-072).

    Each entry is embedded on write; `search()` ranks by cosine similarity so the
    planner and composer see the *relevant* facts/preferences/corrections for a
    mission rather than the whole store.
    """
    def __init__(self):
        self._entries: List[MemoryEntry] = []
        self._vectors: dict = {}   # memory_id -> unit vector

    async def add(self, entry: MemoryEntry) -> None:
        self._entries.append(entry)
        try:
            from nexora.core.embeddings import embed
            self._vectors[entry.memory_id] = (await embed([entry.content]))[0]
        except Exception:
            pass

    async def all(self) -> List[MemoryEntry]:
        return list(self._entries)

    async def search(self, query: str, k: int = 5,
                     scope: MemoryScope | None = None,
                     types: List[MemoryType] | None = None) -> List[MemoryEntry]:
        pool = [e for e in self._entries
                if (scope is None or e.scope == scope)
                and (types is None or e.type in types)]
        if not pool or not query.strip():
            return pool[:k]
        from nexora.core.embeddings import cosine, embed
        try:
            qv = (await embed([query]))[0]
        except Exception:
            return pool[:k]
        scored = []
        for e in pool:
            v = self._vectors.get(e.memory_id)
            if v is None:
                try:
                    v = (await embed([e.content]))[0]
                    self._vectors[e.memory_id] = v
                except Exception:
                    v = None
            scored.append((cosine(qv, v) if v else 0.0, e))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [e for score, e in scored[:k] if score > 0.05] or pool[:k]

    def clear(self):
        self._entries.clear()
        self._vectors.clear()

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