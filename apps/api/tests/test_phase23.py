"""Phase 23 — semantic (vector) organizational memory (ADR-072)."""
import asyncio

from nexora.core.embeddings import embed, cosine, _hashed
from nexora.core.memory import InMemoryMemoryStore
from nexora.core.constitution_builder import ConstitutionBuilder
from nexora.core.capability_network import CapabilityNetwork
from packages.core.models import MemoryEntry, MemoryType, MemoryScope, MissionIntent


def test_hashed_embedding_is_deterministic_and_unit():
    a = _hashed("launch the new product next friday")
    b = _hashed("launch the new product next friday")
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6


def test_embed_fallback_ranks_related_text_higher():
    vecs = asyncio.run(embed([
        "quarterly revenue and financial forecast",
        "book a table at an italian restaurant",
        "revenue projections for the next quarter",
    ]))
    q, unrelated, related = vecs
    assert cosine(q, related) > cosine(q, unrelated)


def test_memory_search_returns_relevant_entries_first():
    store = InMemoryMemoryStore()
    asyncio.run(store.add(MemoryEntry(type=MemoryType.PREFERENCE, scope=MemoryScope.ORG,
                                      content="Always price budgets in USD, not local currency.")))
    asyncio.run(store.add(MemoryEntry(type=MemoryType.PREFERENCE, scope=MemoryScope.ORG,
                                      content="Prefer vegetarian catering for team events.")))
    asyncio.run(store.add(MemoryEntry(type=MemoryType.FACT, scope=MemoryScope.ORG,
                                      content="Our fiscal year ends in March.")))

    hits = asyncio.run(store.search("prepare a travel budget spreadsheet", k=2))
    assert hits
    assert "USD" in hits[0].content


def test_constitution_builder_populates_relevant_memories():
    store = InMemoryMemoryStore()
    asyncio.run(store.add(MemoryEntry(type=MemoryType.POLICY, scope=MemoryScope.ORG,
                                      content="Never contact competitors directly during research.")))
    con = asyncio.run(ConstitutionBuilder(CapabilityNetwork(), store).build(
        "m1", MissionIntent(objective="research the competitive landscape for our product")))
    assert any("competitor" in m.lower() for m in con.relevant_memories)


def test_memory_search_empty_store_is_safe():
    store = InMemoryMemoryStore()
    assert asyncio.run(store.search("anything", k=3)) == []
