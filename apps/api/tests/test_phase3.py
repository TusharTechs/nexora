import asyncio
import time
from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient
from nexora.main import app, runtime, repo, bus
from packages.core.models import Mission, MissionConstitution, MissionNode, MissionState, ExecutionMode

def run(c): return asyncio.run(c)

async def post_and_wait(ac, goal, timeout=10.0):
    r = await ac.post("/api/v1/missions", json={"goal": goal, "execution_mode": "MOCK"})
    assert r.status_code == 200
    mid = r.json()["mission_id"]
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if d["state"] in ("COMPLETED", "FAILED", "PARTIAL_SUCCESS"):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError("mission did not finish")

def test_conditional_branch_true_and_false():
    async def inner():
        runtime.registry.provider.fail_caps = {}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac,
                "Investigate: search emails and drive files, write the incident report, "
                "schedule a war room if urgent emails exist, and prepare a refund brief if refund requests exist.")
            caps = {n["capability_id"]: n for n in d["nodes"]}
            war_rooms = [n for n in d["nodes"] if n["capability_id"] == "calendar.create_event" and n.get("condition")]
            refunds = [n for n in d["nodes"] if n["capability_id"] == "docs.create" and n.get("condition")]
            assert war_rooms and war_rooms[0]["status"] == "SUCCESS"     # 'URGENT' matches seed
            assert refunds and refunds[0]["status"] == "SKIPPED"         # no 'refund' in seed
            assert d["state"] == "COMPLETED"
            assert any(n.get("condition") for n in d["nodes"])
    run(inner())

def test_failure_cascades_to_dependents():
    async def inner():
        runtime.registry.provider.fail_caps = {"gmail.search": 99}
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                d = await post_and_wait(ac, "Search emails and drive files then write the incident report.")
                docs = [n for n in d["nodes"] if n["capability_id"] == "docs.create"]
                assert docs[0]["status"] == "SKIPPED"   # dependency failed -> skipped
                assert d["state"] in ("FAILED", "PARTIAL_SUCCESS")
                assert d["health"]["failed_nodes"], "health must list failed nodes"
        finally:
            runtime.registry.provider.fail_caps = {}
    run(inner())

def test_retry_then_success():
    async def inner():
        runtime.registry.provider.fail_caps = {"sheets.create": 1}
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                d = await post_and_wait(ac, "Create a tracker sheet.")
                node = next(n for n in d["nodes"] if n["capability_id"] == "sheets.create")
                assert node["status"] == "SUCCESS"
                assert node["retries"] == 1
                assert d["health"]["retry_count"] >= 1
        finally:
            runtime.registry.provider.fail_caps = {}
    run(inner())

def test_budget_circuit_breaker():
    async def inner():
        m = Mission(goal="x", execution_mode=ExecutionMode.MOCK)
        m.constitution = MissionConstitution(mission_id=m.mission_id, budget_usd=0.0,
                                             allowed_capabilities=["docs.create"])
        node = MissionNode(capability_id="docs.create", inputs={"title": "t", "content": "c"})
        m.nodes.append(node)
        m.state = MissionState.EXECUTING
        await repo.save(m)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/internal/execute_node", json={"mission_id": m.mission_id, "node_id": node.node_id})
        stored = await repo.get(m.mission_id)
        assert stored.nodes[0].status == "FAILED"
        assert stored.state == MissionState.FAILED
        assert stored.health.budget_remaining_usd <= 0.0
    run(inner())

def test_event_bus_fanout():
    async def inner():
        q = bus.subscribe()
        await bus.publish("TEST.EVENT", {"mission_id": "mX"})
        rec = q.get_nowait()
        assert rec["event_type"] == "TEST.EVENT"
        bus.unsubscribe(q)
    run(inner())

def test_websocket_snapshot():
    with TestClient(app) as client:
        r = client.post("/api/v1/missions", json={"goal": "Write the incident report.", "execution_mode": "MOCK"})
        mid = r.json()["mission_id"]
        with client.websocket_connect(f"/api/v1/missions/{mid}/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert msg["mission"]["mission_id"] == mid
