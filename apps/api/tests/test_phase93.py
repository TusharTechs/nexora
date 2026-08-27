import asyncio
import tempfile
import time
from httpx import ASGITransport, AsyncClient

from nexora.core.capability_network import CapabilityNetwork
from nexora.core.llm_compiler import LLMWorkflowCompiler
from nexora.core.model_router import ModelRouter
from nexora.main import app
from packages.core.models import MissionConstitution, MissionIntent

def run(c): return asyncio.run(c)

CANNED = '''Here is a plan:
{"nodes":[
 {"capability_id":"gmail.search","depends_on":[]},
 {"capability_id":"docs.create","depends_on":["gmail.search"]},
 {"capability_id":"vault.search","depends_on":[]},
 {"capability_id":"docs.create","depends_on":["gmail.search","vault.search"]}
]}'''

def test_llm_compiler_parses_and_validates():
    async def inner():
        net = CapabilityNetwork()
        comp = LLMWorkflowCompiler(net, ModelRouter(), api_key="test", call_fn=lambda p: CANNED)
        constitution = MissionConstitution(mission_id="m", allowed_capabilities=net.ids())
        nodes = await comp.compile("x", MissionIntent(objective="x"), constitution)
        assert nodes is not None
        caps = [n.capability_id for n in nodes]
        assert "vault.search" not in caps                      # unknown dropped
        doc = next(n for n in nodes if n.capability_id == "docs.create")
        g = next(n for n in nodes if n.capability_id == "gmail.search")
        assert g.node_id in doc.depends_on                     # UUID deps (ADR-048)
        assert "vault.search" not in str(doc.depends_on)
    run(inner())

def test_llm_compiler_fallback_without_key():
    async def inner():
        import os
        os.environ.pop("GEMINI_API_KEY", None)
        net = CapabilityNetwork()
        comp = LLMWorkflowCompiler(net, ModelRouter())
        nodes = await comp.compile("write the incident report",
                                   MissionIntent(objective="x"),
                                   MissionConstitution(mission_id="m", allowed_capabilities=net.ids()))
        assert nodes is None
    run(inner())

def test_workspace_uri_created_in_mock():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={"goal": "Write the incident report.", "execution_mode": "MOCK"})
            assert r.json()["workspace_uri"].startswith("mock://workspace/")
    run(inner())

def test_auth_status_endpoint():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/auth/status")
            assert r.status_code == 200
            assert "connected" in r.json()
    run(inner())

def test_live_provider_raises_without_creds():
    from nexora.core.credential_store import LocalCredentialStore
    from nexora.providers.live_workspace import LiveProviderConfigError, LiveWorkspaceProvider
    store = LocalCredentialStore(path=tempfile.mktemp())
    p = LiveWorkspaceProvider(store)
    async def inner():
        try:
            await p.create_document("m", "n", "t", "c")
            assert False, "should raise"
        except LiveProviderConfigError:
            pass
    run(inner())

def test_business_launch_scenario_end_to_end():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "I'm starting my new business project tomorrow. Prepare everything I need: "
                        "business plan doc, learning materials, budget sheet, pitch deck, kickoff meeting, and tasks.",
                "execution_mode": "MOCK"})
            mid = r.json()["mission_id"]
            start = time.time()
            while time.time() - start < 15:
                d = (await ac.get(f"/api/v1/missions/{mid}")).json()
                if d["state"] in ("COMPLETED", "FAILED", "PARTIAL_SUCCESS"):
                    break
                await asyncio.sleep(0.2)
            assert d["state"] == "COMPLETED"
            types = {a["type"] for a in d["artifacts"]}
            assert {"DOC", "SHEET", "SLIDES", "EVENT", "TASK"} <= types
    run(inner())