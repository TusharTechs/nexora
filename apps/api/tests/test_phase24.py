"""Phase 24 — background mission creation + self-grading benchmark scorecard."""
import asyncio
import time

from httpx import ASGITransport, AsyncClient

from nexora.main import app

TERMINAL = {"COMPLETED", "PARTIAL_SUCCESS", "FAILED"}


def test_background_mission_returns_immediately_then_completes():
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=30) as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Search emails and write a short summary document.",
                "execution_mode": "MOCK", "background": True})
            assert r.status_code == 200
            body = r.json()
            mid = body["mission_id"]
            # Returned before planning finished
            assert body["state"] in ("CREATED", "INTERPRETING", "PLANNING")
            assert not body["nodes"]

            for _ in range(60):
                await asyncio.sleep(0.5)
                d = (await ac.get(f"/api/v1/missions/{mid}")).json()
                if d["state"] in TERMINAL:
                    break
            assert d["state"] in TERMINAL
            assert d["nodes"]
    asyncio.run(_run())


def test_run_all_benchmarks_scorecard():
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as ac:
            r = await ac.post("/api/v1/benchmarks/run-all")
            assert r.status_code == 200
            sc = r.json()
            assert sc["total"] == len(sc["results"])
            assert 0.0 <= sc["pass_rate"] <= 1.0
            assert all("benchmark_name" in x for x in sc["results"])
    asyncio.run(_run())
