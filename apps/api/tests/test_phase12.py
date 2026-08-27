import asyncio
from nexora.core.context_discovery import ContextDiscoveryService, ContextBundle


class MockProvider:
    async def search_files(self, query):
        return [
            {"id": "f1", "name": "Ghost Run Concept.docx", "type": "docx"},
            {"id": "f2", "name": "Launch Notes.md", "type": "md"},
        ]

    async def search_emails(self, query, max_results):
        return [
            {"id": "e1", "subject": "Ghost Run kickoff", "snippet": "Meeting scheduled for..."},
            {"id": "e2", "subject": "Market research", "snippet": "Competitors include..."},
        ]


class EmptyProvider:
    async def search_files(self, query):
        return []

    async def search_emails(self, query, max_results):
        return []


class FailingProvider:
    async def search_files(self, query):
        raise RuntimeError("Drive unavailable")

    async def search_emails(self, query, max_results):
        raise RuntimeError("Gmail unavailable")


def run(c): return asyncio.run(c)


def test_context_discovery_finds_items():
    async def inner():
        svc = ContextDiscoveryService(MockProvider())
        bundle = await svc.discover("Evaluate Ghost Run commercial viability")
        assert isinstance(bundle, ContextBundle)
        assert len(bundle.drive_items) == 2
        assert len(bundle.gmail_items) == 2
        assert "Ghost Run" in " ".join(bundle.goal_entities) or "Ghost" in " ".join(bundle.goal_entities)
    run(inner())


def test_context_discovery_empty_results():
    async def inner():
        svc = ContextDiscoveryService(EmptyProvider())
        bundle = await svc.discover("Prepare investor pitch")
        assert isinstance(bundle, ContextBundle)
        assert len(bundle.drive_items) == 0
        assert len(bundle.gmail_items) == 0
        assert "No relevant" in bundle.summary or bundle.summary == ""
    run(inner())


def test_context_discovery_provider_failure_graceful():
    async def inner():
        svc = ContextDiscoveryService(FailingProvider())
        bundle = await svc.discover("Schedule meeting")
        assert isinstance(bundle, ContextBundle)
        # Should not raise — returns empty bundle
        assert len(bundle.drive_items) == 0
        assert len(bundle.gmail_items) == 0
    run(inner())


def test_context_discovery_extracts_entities():
    async def inner():
        svc = ContextDiscoveryService(MockProvider())
        bundle = await svc.discover('Evaluate "Project Aurora" for launch on 2026-10-15 with alex@acme.dev')
        # Should extract quoted phrase, date, email
        entities_lower = [e.lower() for e in bundle.goal_entities]
        assert any("project aurora" in e for e in entities_lower)
        assert any("2026" in e or "10" in e for e in entities_lower)
        assert any("alex@acme.dev" in e for e in entities_lower)
    run(inner())


def test_context_bundle_human_summary():
    async def inner():
        svc = ContextDiscoveryService(MockProvider())
        bundle = await svc.discover("Ghost Run launch")
        summary = bundle.to_human_summary()
        assert "Drive" in summary or "Gmail" in summary
        assert "Ghost Run" in summary or "ghost run" in summary.lower()
    run(inner())