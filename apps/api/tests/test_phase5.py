import asyncio
import time
from httpx import ASGITransport, AsyncClient
from nexora.main import app, runtime

def run(c): return asyncio.run(c)

async def wait_state(ac, mid, terminal=("COMPLETED", "FAILED", "PARTIAL_SUCCESS"), timeout=12.0):
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if d["state"] in terminal:
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError("mission did not finish")

async def wait_for(ac, mid, pred, timeout=12.0):
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if pred(d):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError("condition not met")

def test_calendar_failure_replans_to_task():
    async def inner():
        runtime.registry.provider.fail_caps = {"calendar.create_event": 99}
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post("/api/v1/missions", json={
                    "goal": "Search emails and drive files, schedule a sync meeting, then write the incident report.",
                    "execution_mode": "MOCK"})
                mid = r.json()["mission_id"]
                d = await wait_state(ac, mid)
                assert d["state"] == "COMPLETED"
                cal = next(n for n in d["nodes"] if n["capability_id"] == "calendar.create_event")
                assert cal["status"] == "FAILED" and cal["replaced_by"]
                task = next(n for n in d["nodes"] if n["capability_id"] == "tasks.create")
                assert task["status"] == "SUCCESS"
                types = [a["type"] for a in d["artifacts"]]
                assert "TASK" in types and "DOC" in types
                assert d["replan_count"] >= 1
                ev = (await ac.get(f"/api/v1/missions/{mid}/events")).json()
                assert any(e["event_type"] == "MISSION.ENVIRONMENT_CHANGE_DETECTED" for e in ev)
        finally:
            runtime.registry.provider.fail_caps = {}
    run(inner())

def test_send_rejection_replans_to_draft():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Search emails then send a status email to the customer.", "execution_mode": "MOCK"})
            mid = r.json()["mission_id"]
            d = await wait_for(ac, mid, lambda x: any(n["status"] == "WAITING_APPROVAL" for n in x["nodes"]))
            node = next(n for n in d["nodes"] if n["capability_id"] == "gmail.send")
            await ac.post(f"/api/v1/missions/{mid}/approvals/{node['node_id']}", json={"approved": False})
            d2 = await wait_state(ac, mid)
            assert d2["state"] == "COMPLETED"
            send = next(n for n in d2["nodes"] if n["capability_id"] == "gmail.send")
            draft = next(n for n in d2["nodes"] if n["capability_id"] == "gmail.draft")
            assert send["status"] == "FAILED" and send["replaced_by"] == draft["node_id"]
            assert draft["status"] == "SUCCESS"
            assert any(a["type"] == "DRAFT" for a in d2["artifacts"])
    run(inner())

def test_intervention_stop_external():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Search emails then send a status email to the customer.", "execution_mode": "MOCK"})
            mid = r.json()["mission_id"]
            await wait_for(ac, mid, lambda x: any(n["status"] == "WAITING_APPROVAL" for n in x["nodes"]))
            ir = await ac.post(f"/api/v1/missions/{mid}/intervene",
                               json={"instruction": "Stop all external communication."})
            assert ir.status_code == 200
            d = await wait_state(ac, mid)
            assert d["state"] == "COMPLETED"
            assert "gmail.send" in d["constitution"]["forbidden_actions"]
            send = next(n for n in d["nodes"] if n["capability_id"] == "gmail.send")
            draft = next(n for n in d["nodes"] if n["capability_id"] == "gmail.draft")
            assert send["status"] == "SKIPPED"
            assert draft["status"] == "SUCCESS"
    run(inner())

def test_intervention_add_sheet_mid_mission():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Search emails, send a status email, and write the report.", "execution_mode": "MOCK"})
            mid = r.json()["mission_id"]
            await wait_for(ac, mid, lambda x: any(n["status"] == "WAITING_APPROVAL" for n in x["nodes"]))
            ir = await ac.post(f"/api/v1/missions/{mid}/intervene", json={"instruction": "Add a tracker sheet."})
            assert ir.status_code == 200
            d = await wait_for(ac, mid, lambda x: any(
                n["capability_id"] == "sheets.create" and n["status"] == "SUCCESS" for n in x["nodes"]))
            # mission still blocked on approval; now approve and finish
            send = next(n for n in d["nodes"] if n["capability_id"] == "gmail.send")
            await ac.post(f"/api/v1/missions/{mid}/approvals/{send['node_id']}", json={"approved": True})
            d2 = await wait_state(ac, mid)
            assert d2["state"] == "COMPLETED"
            assert any(a["type"] == "SHEET" for a in d2["artifacts"])
    run(inner())

def test_retry_success_does_not_replan():
    async def inner():
        runtime.registry.provider.fail_caps = {"sheets.create": 1}
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post("/api/v1/missions", json={
                    "goal": "Create a tracker sheet.", "execution_mode": "MOCK"})
                d = await wait_state(ac, r.json()["mission_id"])
                assert d["state"] == "COMPLETED"
                assert d["replan_count"] == 0
                assert d["health"]["retry_count"] >= 1
        finally:
            runtime.registry.provider.fail_caps = {}
    run(inner())