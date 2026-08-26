import asyncio
import time
from httpx import ASGITransport, AsyncClient
from nexora.main import app, runtime

def run(c): return asyncio.run(c)

DEMO2 = ("A customer sent a screenshot of a production error. Investigate, analyze the "
         "screenshot, estimate impact, create the incident report and a status presentation, "
         "notify the team, and create follow-up tasks.")

async def post_and_wait(ac, goal, timeout=15.0):
    r = await ac.post("/api/v1/missions", json={"goal": goal, "execution_mode": "MOCK"})
    assert r.status_code == 200
    mid = r.json()["mission_id"]
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if d["state"] in ("COMPLETED", "FAILED", "PARTIAL_SUCCESS"):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError()

def test_multimodal_extracts_error_code():
    async def inner():
        runtime.registry.provider.fail_caps = {}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac, DEMO2)
            mm = next(n for n in d["nodes"] if n["capability_id"] == "multimodal.analyze")
            assert mm["status"] == "SUCCESS"
            assert mm["outputs"]["analysis"]["error_code"] == "DB_TIMEOUT"
    run(inner())

def test_incident_dag_produces_advanced_artifacts():
    async def inner():
        runtime.registry.provider.fail_caps = {}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac, DEMO2)
            assert d["state"] == "COMPLETED"
            types = {a["type"] for a in d["artifacts"]}
            assert {"ANALYSIS", "DOC", "SLIDES", "CHAT", "TASK"} <= types
    run(inner())

def test_impact_analysis_reads_sheet():
    async def inner():
        runtime.registry.provider.fail_caps = {}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac, DEMO2)
            sr = next(n for n in d["nodes"] if n["capability_id"] == "sheets.read")
            assert sr["status"] == "SUCCESS"
            assert ["orders_affected", 1240] in sr["outputs"]["rows"]
    run(inner())

def test_creative_capabilities_autonomous():
    async def inner():
        runtime.registry.provider.fail_caps = {}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac, "Prepare a launch video and an audio briefing.")
            types = {a["type"] for a in d["artifacts"]}
            assert {"VIDEO", "AUDIO"} <= types
    run(inner())

def test_people_and_forms():
    async def inner():
        runtime.registry.provider.fail_caps = {}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac, "Search the stakeholder contacts and create a survey form.")
            ppl = next(n for n in d["nodes"] if n["capability_id"] == "people.search")
            frm = next(n for n in d["nodes"] if n["capability_id"] == "forms.create")
            assert ppl["status"] == "SUCCESS" and ppl["outputs"]["people"]
            assert frm["status"] == "SUCCESS"
            assert any(a["type"] == "FORM" for a in d["artifacts"])
    run(inner())

def test_capability_network_includes_fabric():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/capabilities")
            ids = {c["capability_id"] for c in r.json()}
            assert {"veo.generate_video", "lyria.generate_audio", "multimodal.analyze",
                    "slides.create", "chat.notify", "people.search", "forms.create"} <= ids
    run(inner())