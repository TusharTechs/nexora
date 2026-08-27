import asyncio, time
from httpx import ASGITransport, AsyncClient
from nexora.main import app

def run(c): return asyncio.run(c)

async def wait_state(ac, mid, timeout=15.0):
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if d["state"] in ("COMPLETED", "FAILED", "PARTIAL_SUCCESS"):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError()

def test_attachment_forces_multimodal():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Prepare my business launch.",
                "execution_mode": "MOCK",
                "attachment": {"name": "err.png", "type": "image/png", "text": ""}})
            mid = r.json()["mission_id"]
            d = await wait_state(ac, mid)
            mm = next((n for n in d["nodes"] if n["capability_id"] == "multimodal.analyze"), None)
            assert mm is not None and mm["status"] == "SUCCESS"
            assert mm["outputs"]["analysis"]["error_code"] == "DB_TIMEOUT"
    run(inner())