import asyncio
import time
from httpx import ASGITransport, AsyncClient
from nexora.main import app, runtime, memory as memory_store

def run(c): return asyncio.run(c)

async def wait_state(ac, mid, timeout=12.0):
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if d["state"] in ("COMPLETED", "FAILED", "PARTIAL_SUCCESS"):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError()

async def wait_for(ac, mid, pred, timeout=12.0):
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if pred(d):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError()

def test_teach_approval_policy_enforced():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/memory/teach",
                              json={"instruction": "Always require my approval before scheduling meetings."})
            assert r.status_code == 200
            assert r.json()["effect"] == "require_approval"
            m = await ac.post("/api/v1/missions", json={
                "goal": "Schedule a sync meeting.", "execution_mode": "MOCK"})
            mid = m.json()["mission_id"]
            d = await wait_for(ac, mid, lambda x: any(n["status"] == "WAITING_APPROVAL" for n in x["nodes"]))
            node = next(n for n in d["nodes"] if n["capability_id"] == "calendar.create_event")
            await ac.post(f"/api/v1/missions/{mid}/approvals/{node['node_id']}", json={"approved": True})
            d2 = await wait_state(ac, mid)
            assert d2["state"] == "COMPLETED"
    run(inner())

def test_teach_forbid_policy_enforced():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/api/v1/memory/teach", json={"instruction": "Never create sheets."})
            m = await ac.post("/api/v1/missions", json={
                "goal": "Create a tracker sheet.", "execution_mode": "MOCK"})
            d = await wait_state(ac, m.json()["mission_id"])
            assert "sheets.create" in d["constitution"]["forbidden_actions"]
            node = next(n for n in d["nodes"] if n["capability_id"] == "sheets.create")
            assert node["status"] == "FAILED"
    run(inner())

def test_rejection_records_correction_memory():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            m = await ac.post("/api/v1/missions", json={
                "goal": "Search emails then send a status email to the customer.", "execution_mode": "MOCK"})
            mid = m.json()["mission_id"]
            d = await wait_for(ac, mid, lambda x: any(n["status"] == "WAITING_APPROVAL" for n in x["nodes"]))
            node = next(n for n in d["nodes"] if n["capability_id"] == "gmail.send")
            await ac.post(f"/api/v1/missions/{mid}/approvals/{node['node_id']}", json={"approved": False})
            await wait_state(ac, mid)
            mem = (await ac.get("/api/v1/memory")).json()
            assert any(e["type"] == "CORRECTION" and e["capability"] == "gmail.send" for e in mem)
    run(inner())

def test_forge_and_rerun_template():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            m = await ac.post("/api/v1/missions", json={
                "goal": "Search emails then write the incident report.", "execution_mode": "MOCK"})
            d = await wait_state(ac, m.json()["mission_id"])
            assert d["state"] == "COMPLETED"
            f = await ac.post(f"/api/v1/missions/{d['mission_id']}/forge")
            assert f.status_code == 200
            tid = f.json()["template_id"]
            assert f.json()["expected_cost_usd"] > 0
            wf = (await ac.get("/api/v1/workflows")).json()
            assert any(w["template_id"] == tid for w in wf)
            r = await ac.post(f"/api/v1/workflows/{tid}/run")
            assert r.status_code == 200
            d2 = await wait_state(ac, r.json()["mission_id"])
            assert d2["state"] == "COMPLETED"
            assert {n["capability_id"] for n in d2["nodes"]} == {"gmail.search", "docs.create"}
    run(inner())

def test_replay_reconstructs_without_mutation():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            m = await ac.post("/api/v1/missions", json={
                "goal": "Write the incident report.", "execution_mode": "MOCK"})
            d = await wait_state(ac, m.json()["mission_id"])
            orig_uri = d["artifacts"][0]["uri"]
            r = await ac.post(f"/api/v1/missions/{d['mission_id']}/replay")
            assert r.status_code == 200
            rd = await wait_state(ac, r.json()["mission_id"])
            assert rd["state"] == "COMPLETED"
            assert rd["execution_mode"] == "REPLAY"
            assert rd["artifacts"][0]["uri"] == orig_uri
            assert all(rec["execution_mode"] == "REPLAY" for rec in rd["receipts"])
    run(inner())

def test_evidence_sources_reference_artifacts():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            m = await ac.post("/api/v1/missions", json={
                "goal": "Write the incident report.", "execution_mode": "MOCK"})
            d = await wait_state(ac, m.json()["mission_id"])
            art_ids = {a["artifact_id"] for a in d["artifacts"]}
            for e in d["evidence"]:
                assert set(e["sources"]) <= art_ids
    run(inner())