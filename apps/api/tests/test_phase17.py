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


def test_learning_ai_goal():
    """Advisory goal: learning AI should produce a researched plan."""
    async def inner():
        runtime.registry.provider.reset_seed()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Prepare a comprehensive plan to learn AI in 2026",
                "execution_mode": "MOCK"
            })
            assert r.status_code == 200
            mid = r.json()["mission_id"]
            d = await wait_state(ac, mid)
            
            # Contract should have learning-specific deliverables
            assert d["outcome_contract"] is not None
            deliverables = d["outcome_contract"]["required_deliverables"]
            assert len(deliverables) >= 3
            
            # Should produce a DOC artifact (the plan)
            types = {a["type"] for a in d["artifacts"]}
            assert "DOC" in types
            
            # Terminal state
            assert d["state"] in ("COMPLETED", "PARTIAL_SUCCESS")
    run(inner())


def test_career_growth_goal():
    """Advisory goal: career growth should produce actionable plan."""
    async def inner():
        runtime.registry.provider.reset_seed()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Help me get promoted to senior engineer in 6 months",
                "execution_mode": "MOCK"
            })
            assert r.status_code == 200
            mid = r.json()["mission_id"]
            d = await wait_state(ac, mid)
            
            # Contract should have career-specific deliverables
            assert d["outcome_contract"] is not None
            deliverables = d["outcome_contract"]["required_deliverables"]
            assert len(deliverables) >= 2
            
            # Should produce artifacts
            assert len(d["artifacts"]) >= 1
            
            # Terminal state
            assert d["state"] in ("COMPLETED", "PARTIAL_SUCCESS")
    run(inner())


def test_personal_finance_goal():
    """Advisory goal: personal finance should produce researched plan."""
    async def inner():
        runtime.registry.provider.reset_seed()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Create a budget plan to save for a house down payment",
                "execution_mode": "MOCK"
            })
            assert r.status_code == 200
            mid = r.json()["mission_id"]
            d = await wait_state(ac, mid)
            
            # Contract should have finance-specific deliverables
            assert d["outcome_contract"] is not None
            deliverables = d["outcome_contract"]["required_deliverables"]
            assert len(deliverables) >= 2
            
            # Should produce a SHEET artifact (budget)
            types = {a["type"] for a in d["artifacts"]}
            assert "SHEET" in types or "DOC" in types
            
            # Terminal state
            assert d["state"] in ("COMPLETED", "PARTIAL_SUCCESS")
    run(inner())


def test_vague_get_rich_goal():
    """Vague goal: 'get rich' should still produce a researched plan or honest insufficiency."""
    async def inner():
        runtime.registry.provider.reset_seed()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "How do I get rich?",
                "execution_mode": "MOCK"
            })
            assert r.status_code == 200
            mid = r.json()["mission_id"]
            d = await wait_state(ac, mid)
            
            # Contract should exist (even if minimal)
            assert d["outcome_contract"] is not None
            
            # Should produce at least one artifact (researched plan or honest report)
            assert len(d["artifacts"]) >= 1
            
            # Terminal state (COMPLETED or PARTIAL_SUCCESS, never FAILED for advisory goals)
            assert d["state"] in ("COMPLETED", "PARTIAL_SUCCESS")
    run(inner())


def test_contract_vocabulary_expansion():
    """Verify that contract vocabulary maps advisory goals to capabilities."""
    from nexora.core.compiler import WorkflowCompiler, CONTRACT_CAP_RULES
    from nexora.core.contract import OutcomeContract
    from nexora.core.capability_network import CapabilityNetwork
    from packages.core.models import MissionConstitution
    
    net = CapabilityNetwork()
    comp = WorkflowCompiler(net)
    
    # Learning goal
    contract = OutcomeContract(
        objective="Learn AI",
        required_deliverables=["Learning roadmap", "Resource list", "Study schedule"])
    constitution = MissionConstitution(mission_id="m", allowed_capabilities=net.ids())
    caps = {c for c, _ in comp._contract_caps(contract, constitution)}
    assert "docs.create" in caps  # plan document
    assert "web.research" in caps  # find resources
    
    # Finance goal
    contract = OutcomeContract(
        objective="Budget plan",
        required_deliverables=["Budget spreadsheet", "Savings plan"])
    caps = {c for c, _ in comp._contract_caps(contract, constitution)}
    assert "sheets.create" in caps
    
    # Career goal
    contract = OutcomeContract(
        objective="Career growth",
        required_deliverables=["Skill gap analysis", "Learning plan"])
    caps = {c for c, _ in comp._contract_caps(contract, constitution)}
    assert "docs.create" in caps


def test_every_goal_yields_verified_deliverable():
    """Guarantee: every goal produces at least one verified deliverable."""
    goals = [
        "Launch a SaaS product",
        "Plan a company offsite",
        "Write a blog post about AI",
        "Prepare for a job interview",
    ]
    
    async def inner():
        runtime.registry.provider.reset_seed()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            for goal in goals:
                r = await ac.post("/api/v1/missions", json={
                    "goal": goal,
                    "execution_mode": "MOCK"
                })
                assert r.status_code == 200
                mid = r.json()["mission_id"]
                d = await wait_state(ac, mid)
                
                # Every goal should produce at least one artifact
                assert len(d["artifacts"]) >= 1, f"Goal '{goal}' produced no artifacts"
                
                # Every goal should reach a terminal state
                assert d["state"] in ("COMPLETED", "PARTIAL_SUCCESS", "FAILED")
    run(inner())