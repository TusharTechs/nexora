"""Phase 25 — Agent Engine wiring + Memory Bank store (ADR-073).

Hermetic: no Agent Engine is configured in the test env, so we assert the
graceful in-process behaviour and the factory routing.
"""
import asyncio
import os

from nexora.core.memory_bank import build_memory_store, memory_bank_available, VertexMemoryBankStore
from nexora.core.memory import InMemoryMemoryStore
from nexora.core.adk_runtime import _agent_engine_id
from packages.core.models import MemoryEntry, MemoryType, MemoryScope


def test_factory_returns_in_memory_without_config():
    assert not memory_bank_available()
    assert isinstance(build_memory_store(), InMemoryMemoryStore)


def test_agent_engine_id_parses_bare_and_full():
    os.environ["NEXORA_AGENT_ENGINE"] = "3619105744743301120"
    try:
        assert _agent_engine_id() == "3619105744743301120"
        os.environ["NEXORA_AGENT_ENGINE"] = \
            "projects/p/locations/us-central1/reasoningEngines/999"
        assert _agent_engine_id() == "999"
    finally:
        os.environ["NEXORA_AGENT_ENGINE"] = ""


def test_memory_bank_store_falls_back_to_local_search_when_unavailable():
    """VertexMemoryBankStore keeps working (local vector search) with no backend."""
    store = VertexMemoryBankStore()   # constructs; _bank() is lazy
    asyncio.run(store.add(MemoryEntry(type=MemoryType.PREFERENCE, scope=MemoryScope.ORG,
                                      content="Always price budgets in USD.")))
    hits = asyncio.run(store.search("prepare a travel budget", k=1))
    assert hits and "USD" in hits[0].content
    # typed behaviour preserved
    asyncio.run(store.add(MemoryEntry(type=MemoryType.POLICY, scope=MemoryScope.ORG,
                                      content="no email", capability="gmail.send",
                                      effect="forbid")))
    assert "gmail.send" in store.forbiddens()
