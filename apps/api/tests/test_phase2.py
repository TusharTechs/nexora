import asyncio
import time
from httpx import ASGITransport, AsyncClient
from nexora.main import app, runtime, repo
from packages.core.models import Mission, MissionConstitution, MissionNode, MissionState, ExecutionMode

def run(c): return asyncio.run(c)

GOAL = ("Investigate the incident: search emails and drive files, create a tracker sheet, "
        "schedule a sync meeting, then write the incident report.")

async def post_and_wait(ac, goal, timeout=10.0):
    r = await ac.post("/api/v1/missions", json={"goal": goal, "execution_mode": "MOCK"})
    assert r.status_code == 200
    mid = r.json()["mission_id"]
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if d["state"] in ("COMPLETED", "FAILED"):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError("mission did not finish")

def test_parallel_dag_and_dependencies():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac, GOAL)
            assert d["state"] == "COMPLETED"
            caps = {n["capability_id"]: n for n in d["nodes"]}
            assert {"gmail.search", "drive.search", "sheets.create", "calendar.create_event", "docs.create"} <= set(caps)
            for synth in ("docs.create", "calendar.create_event"):
                for research in ("gmail.search", "drive.search"):
                    assert caps[research]["completed_at"] <= caps[synth]["started_at"]
            assert sorted(a["type"] for a in d["artifacts"]) == ["DOC", "EVENT", "SHEET"]
            assert len(d["evidence"]) == 3
    run(inner())

def test_parallelism_observed():
    assert runtime.registry.provider.max_concurrency >= 2

def test_events_published():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac, "Write the incident report.")
            ev = (await ac.get(f"/api/v1/missions/{d['mission_id']}/events")).json()
            types = [e["event_type"] for e in ev]
            assert "MISSION.NODE.COMPLETED" in types
            assert "MISSION.COMPLETED" in types
    run(inner())

def test_gmail_send_requires_approval_then_approve():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Search emails then send a status email to the customer.", "execution_mode": "MOCK"})
            mid = r.json()["mission_id"]
            d = None
            for _ in range(50):
                d = (await ac.get(f"/api/v1/missions/{mid}")).json()
                if any(n["status"] == "WAITING_APPROVAL" for n in d["nodes"]):
                    break
                await asyncio.sleep(0.2)
            assert d["state"] == "BLOCKED"
            node = next(n for n in d["nodes"] if n["capability_id"] == "gmail.send")
            a = await ac.post(f"/api/v1/missions/{mid}/approvals/{node['node_id']}", json={"approved": True})
            assert a.status_code == 200
            start = time.time()
            while time.time() - start < 10:
                d2 = (await ac.get(f"/api/v1/missions/{mid}")).json()
                if d2["state"] in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.2)
            assert d2["state"] == "COMPLETED"
            send = next(n for n in d2["nodes"] if n["capability_id"] == "gmail.send")
            assert send["status"] == "SUCCESS" and send["approved"] is True
    run(inner())

def test_worker_endpoint_executes_node():
    async def inner():
        m = Mission(goal="x", execution_mode=ExecutionMode.MOCK)
        m.constitution = MissionConstitution(mission_id=m.mission_id, allowed_capabilities=["docs.create"])
        node = MissionNode(capability_id="docs.create", inputs={"title": "t", "content": "c"})
        m.nodes.append(node)
        m.state = MissionState.EXECUTING
        await repo.save(m)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/internal/execute_node", json={"mission_id": m.mission_id, "node_id": node.node_id})
            assert r.status_code == 200
        stored = await repo.get(m.mission_id)
        assert stored.nodes[0].status == "SUCCESS"
    run(inner())
