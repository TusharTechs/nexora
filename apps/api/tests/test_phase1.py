import asyncio
import time
from httpx import ASGITransport, AsyncClient
from nexora.main import app
from nexora.core.state_machine import MissionStateMachine, InvalidStateTransitionError
from nexora.core.policy_engine import PolicyEngine
from nexora.core.capability_network import CapabilityNetwork
from nexora.agents.verifier import VerificationAgent
from nexora.providers.mock_workspace import MockWorkspaceProvider
from nexora.providers.protocols import ProviderRegistry
from packages.core.models import MissionState, MissionConstitution, MissionIntent

def run(c): return asyncio.run(c)

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

def test_vertical_slice_mock():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac, "Create an incident report for this issue.")
            assert d["state"] == "COMPLETED"
            # Hermetic: no LLM backend, so the interpreter degrades to the goal itself.
            assert "incident report" in d["intent"]["objective"].lower()
            assert d["nodes"][0]["capability_id"] == "docs.create"
            assert d["nodes"][0]["status"] == "SUCCESS"
            assert d["artifacts"][0]["provider"] == "mock"
            assert d["receipts"][0]["policy_decision"] == "ALLOW"
            assert d["verification"]["overall_status"] == "PASS"
            assert d["health"]["completion_percentage"] == 100.0
            assert len(d["evidence"]) == 1
    run(inner())

def test_state_machine_rejects_invalid_transition():
    try:
        MissionStateMachine.transition(MissionState.CREATED, MissionState.COMPLETED)
        assert False
    except InvalidStateTransitionError:
        pass

def test_policy_engine_blocks_forbidden():
    constitution = MissionConstitution(mission_id="m1", forbidden_actions=["docs.create"])
    assert PolicyEngine().evaluate("docs.create", constitution) == "BLOCK"

def test_capability_network_lookup():
    net = CapabilityNetwork()
    assert net.get("docs.create") is not None
    assert net.get("gmail.search") is not None
    assert net.get("vault.search") is None   # enterprise caps arrive later

def test_verifier_fails_when_artifact_missing():
    async def inner():
        v = await VerificationAgent(ProviderRegistry(MockWorkspaceProvider())).verify("m1", MissionIntent(objective="x"), [])
        assert v.overall_status == "FAIL"
    run(inner())
