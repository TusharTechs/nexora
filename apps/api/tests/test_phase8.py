import asyncio
import time
from httpx import ASGITransport, AsyncClient
from nexora.main import app, runtime, registry
from nexora.benchmarks import BENCHMARKS, evaluate_mission
from nexora.providers.acme_labs import AcmeLabsProvider

def run(c): return asyncio.run(c)

async def wait_state(ac, mid, timeout=15.0):
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if d["state"] in ("COMPLETED", "FAILED", "PARTIAL_SUCCESS"):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError()

def test_acme_labs_provider_has_rich_data():
    async def inner():
        provider = AcmeLabsProvider()
        emails = await provider.search_emails("", 20)
        assert len(emails) >= 10
        files = await provider.search_files("")
        assert len(files) >= 8
        people = await provider.search_people("")
        assert len(people) >= 6
        metrics = await provider.read_sheet("metrics", "")
        assert len(metrics) >= 6
    run(inner())

def test_benchmark_incident_response():
    async def inner():
        old_provider = runtime.registry.provider
        runtime.registry.provider = AcmeLabsProvider()
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                bm = next(b for b in BENCHMARKS if b.name == "Incident Response")
                r = await ac.post("/api/v1/missions", json={"goal": bm.goal, "execution_mode": "MOCK"})
                mid = r.json()["mission_id"]
                d = await wait_state(ac, mid)
                mission_obj = await runtime.repo.get(mid)
                result = evaluate_mission(mission_obj, bm)
                assert result["pass"]
                assert result["score"] == 1.0
        finally:
            runtime.registry.provider = old_provider
    run(inner())

def test_benchmark_product_launch():
    async def inner():
        old_provider = runtime.registry.provider
        runtime.registry.provider = AcmeLabsProvider()
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                bm = next(b for b in BENCHMARKS if b.name == "Product Launch Prep")
                r = await ac.post("/api/v1/missions", json={"goal": bm.goal, "execution_mode": "MOCK"})
                mid = r.json()["mission_id"]
                d = await wait_state(ac, mid)
                mission_obj = await runtime.repo.get(mid)
                result = evaluate_mission(mission_obj, bm)
                assert result["pass"]
                assert "ANALYSIS" in result["actual_artifacts"]
                assert "VIDEO" in result["actual_artifacts"]
        finally:
            runtime.registry.provider = old_provider
    run(inner())

def test_benchmark_endpoint():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/benchmarks")
            assert r.status_code == 200
            body = r.json()
            assert len(body) == len(BENCHMARKS)
            assert any(b["name"] == "Incident Response" for b in body)
    run(inner())

def test_run_benchmark_endpoint():
    async def inner():
        old_provider = runtime.registry.provider
        runtime.registry.provider = AcmeLabsProvider()
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                bm = next(b for b in BENCHMARKS if b.name == "Financial Analysis")
                r = await ac.post(f"/api/v1/benchmarks/{bm.name}/run")
                assert r.status_code == 200
                mid = r.json()["mission_id"]
                d = await wait_state(ac, mid)
                er = await ac.get(f"/api/v1/missions/{mid}/benchmark")
                assert er.status_code == 200
                result = er.json()
                assert result["benchmark_name"] == bm.name
                assert result["pass"]
        finally:
            runtime.registry.provider = old_provider
    run(inner())

def test_acme_labs_environment_mode():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Investigate the production outage.",
                "execution_mode": "ACME_LABS"})
            assert r.status_code == 200
            mid = r.json()["mission_id"]
            d = await wait_state(ac, mid)
            assert d["state"] == "COMPLETED"
    run(inner())