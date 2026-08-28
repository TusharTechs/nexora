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


def test_imagen_capability_registered():
    from nexora.core.capability_network import CapabilityNetwork
    from nexora.core.personas import persona_for_capability
    net = CapabilityNetwork()
    cap = net.get("imagen.generate_image")
    assert cap is not None
    assert persona_for_capability("imagen.generate_image").role == "Visual Designer"


def test_mock_generate_image_artifact():
    from nexora.providers.mock_workspace import MockWorkspaceProvider
    async def inner():
        p = MockWorkspaceProvider()
        art = await p.generate_image("m", "n", "tropical island at sunset")
        assert art.type == "IMAGE"
        assert await p.verify_artifact(art)
    run(inner())


def test_travel_goal_produces_images_and_doc():
    async def inner():
        runtime.registry.provider.reset_seed()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "I want to go to the best island in the world. Recommend where I should go "
                        "and prepare a travel brief with pictures.",
                "execution_mode": "MOCK"})
            assert r.status_code == 200
            mid = r.json()["mission_id"]
            d = await wait_state(ac, mid)

            caps = {n["capability_id"] for n in d["nodes"]}
            assert "imagen.generate_image" in caps
            assert "docs.create" in caps

            types = {a["type"] for a in d["artifacts"]}
            assert "IMAGE" in types and "DOC" in types
            assert d["state"] in ("COMPLETED", "PARTIAL_SUCCESS")
    run(inner())