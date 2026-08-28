"""Phase 20: Lyria audio generation tests."""
import asyncio
import time
from httpx import ASGITransport, AsyncClient
from nexora.main import app, runtime


def run(c): return asyncio.run(c)


async def wait_state(ac, mid, timeout=20.0):
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if d["state"] in ("COMPLETED", "FAILED", "PARTIAL_SUCCESS"):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError()


def test_mock_generate_audio_artifact():
    from nexora.providers.mock_workspace import MockWorkspaceProvider
    async def inner():
        p = MockWorkspaceProvider()
        art = await p.generate_audio("m", "n", "executive briefing on quarterly results")
        assert art.type == "AUDIO"
        assert await p.verify_artifact(art)
    run(inner())


def test_briefing_goal_includes_audio_in_mock():
    async def inner():
        runtime.registry.provider.reset_seed()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Give me an audio briefing about recent AI news",
                "execution_mode": "MOCK"})
            assert r.status_code == 200
            mid = r.json()["mission_id"]
            d = await wait_state(ac, mid)

            caps = {n["capability_id"] for n in d["nodes"]}
            # Should include both audio generation and a doc (script)
            assert "lyria.generate_audio" in caps
            assert "docs.create" in caps

            types = {a["type"] for a in d["artifacts"]}
            assert "AUDIO" in types and "DOC" in types
            assert d["state"] in ("COMPLETED", "PARTIAL_SUCCESS")
    run(inner())


def test_travel_goal_does_not_auto_trigger_audio():
    """Audio is opt-in. Island demo should NOT generate audio by default."""
    async def inner():
        runtime.registry.provider.reset_seed()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Recommend the best island in the world with pictures",
                "execution_mode": "MOCK"})
            assert r.status_code == 200
            mid = r.json()["mission_id"]
            d = await wait_state(ac, mid)

            caps = {n["capability_id"] for n in d["nodes"]}
            # Island demo: images OK, audio NO
            assert "lyria.generate_audio" not in caps
    run(inner())


def test_audio_capability_registered():
    from nexora.core.capability_network import CapabilityNetwork
    from nexora.core.personas import persona_for_capability
    net = CapabilityNetwork()
    cap = net.get("lyria.generate_audio")
    assert cap is not None
    assert cap.estimated_cost_usd < 0.10  # Cheap, not Veo-expensive