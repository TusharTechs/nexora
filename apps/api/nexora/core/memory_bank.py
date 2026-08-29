"""Vertex AI Agent Engine Memory Bank backend for organizational memory (ADR-073).

`VertexMemoryBankStore` keeps the local typed behaviour of `InMemoryMemoryStore`
(forbiddens, approval overrides — Memory Bank stores free-text facts, not our
typed effects) and additionally:

- writes every entry's content to **Agent Engine Memory Bank** on `add()`
- serves `search()` from Memory Bank's managed similarity retrieval, falling back
  to the local vector search on any error.

Enabled by NEXORA_MEMORY=memorybank + NEXORA_AGENT_ENGINE=<reasoningEngine id or
full resource name>. Without those it is never constructed.
"""
from __future__ import annotations

import os
from typing import List, Optional

from packages.core.models import MemoryEntry, MemoryScope, MemoryType
from nexora.core.memory import InMemoryMemoryStore


def _engine_resource() -> str:
    v = os.getenv("NEXORA_AGENT_ENGINE", "").strip()
    if not v:
        return ""
    if v.startswith("projects/"):
        return v
    proj = os.getenv("GCP_PROJECT_ID", "")
    loc = os.getenv("GCP_LOCATION", "us-central1")
    return f"projects/{proj}/locations/{loc}/reasoningEngines/{v}"


def memory_bank_available() -> bool:
    return (os.getenv("NEXORA_MEMORY", "") == "memorybank"
            and bool(_engine_resource())
            and bool(os.getenv("GCP_PROJECT_ID")))


class VertexMemoryBankStore(InMemoryMemoryStore):
    def __init__(self):
        super().__init__()
        self._resource = _engine_resource()
        self._loc = os.getenv("GCP_LOCATION", "us-central1")
        self._proj = os.getenv("GCP_PROJECT_ID", "")
        self._scope = {"app": "nexora", "user_id": os.getenv("NEXORA_MEMORY_USER", "default")}
        self._client = None

    def _bank(self):
        if self._client is None:
            import vertexai
            self._client = vertexai.Client(project=self._proj, location=self._loc).agent_engines.memories
        return self._client

    async def add(self, entry: MemoryEntry) -> None:
        await super().add(entry)   # keep local typed behaviour + vector fallback
        if not memory_bank_available():
            return
        try:
            import asyncio
            await asyncio.to_thread(
                self._bank().create,
                name=self._resource, fact=entry.content, scope=self._scope)
        except Exception as e:  # pragma: no cover - network dependent
            from nexora.core.scheduler import _log as _l  # reuse a logger
            _l.warning("memory bank write failed: %s", e)

    async def search(self, query: str, k: int = 5,
                     scope: MemoryScope | None = None,
                     types: Optional[List[MemoryType]] = None) -> List[MemoryEntry]:
        if not memory_bank_available():
            return await super().search(query, k=k, scope=scope, types=types)
        try:
            import asyncio

            from vertexai import types as vtypes
            res = await asyncio.to_thread(
                self._bank().retrieve,
                name=self._resource, scope=self._scope,
                similarity_search_params=vtypes.RetrieveMemoriesRequestSimilaritySearchParams(
                    search_query=query, top_k=k))
            facts: List[str] = []
            for m in res:
                mem = getattr(m, "memory", m)
                fact = getattr(mem, "fact", None)
                if fact:
                    facts.append(fact)
            if facts:
                return [MemoryEntry(type=MemoryType.FACT, scope=MemoryScope.ORG,
                                    content=f, provenance="memory_bank") for f in facts]
        except Exception as e:  # pragma: no cover
            from nexora.core.scheduler import _log as _l
            _l.warning("memory bank retrieve failed, using local search: %s", e)
        return await super().search(query, k=k, scope=scope, types=types)


def build_memory_store():
    if memory_bank_available():
        try:
            return VertexMemoryBankStore()
        except Exception:
            pass
    return InMemoryMemoryStore()
