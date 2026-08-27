import asyncio
from nexora.core.adaptive_replanner import AdaptiveReplanner
from nexora.core.capability_network import CapabilityNetwork
from nexora.core.policy_engine import PolicyEngine
from nexora.agents.critic import PlanCritic
from nexora.core.semantic_verifier import SemanticVerificationReport, DeliverableCheck
from packages.core.models import Mission, MissionIntent, MissionConstitution, MissionNode, MissionState

def run(c): return asyncio.run(c)


def _mission(goal="test", replan_count=0):
    m = Mission(mission_id="m1", goal=goal, execution_mode="MOCK")
    m.intent = MissionIntent(objective=goal)
    m.constitution = MissionConstitution(mission_id="m1", allowed_capabilities=[
        "gmail.search", "drive.search", "docs.create", "sheets.create",
        "web.research", "slides.create", "calendar.create_event",
    ])
    m.replan_count = replan_count
    m.nodes = [
        MissionNode(node_id="n1", capability_id="docs.create", status="SUCCESS"),
    ]
    return m


def _incomplete_report():
    return SemanticVerificationReport(
        complete=False,
        deliverables=[
            DeliverableCheck(name="market research", status="MISSING"),
            DeliverableCheck(name="financial model", status="PARTIAL"),
        ],
        missing_requirements=["market research"],
        recommended_next_actions=["Add web research for market data"],
        rationale="1 missing, 1 partial",
    )


CANNED_FOLLOWUP = '''
{
  "nodes": [
    {"capability_id": "web.research", "depends_on": [],
     "rationale": "Gather market data for missing market research"},
    {"capability_id": "docs.create", "depends_on": ["web.research"],
     "rationale": "Write market research doc"}
  ]
}
'''

CANNED_EMPTY = '{"nodes": []}'


def test_adaptive_replan_proposes_followup():
    async def inner():
        net = CapabilityNetwork()
        policy = PolicyEngine(net)
        critic = PlanCritic(net)
        ar = AdaptiveReplanner(net, policy, critic,
                               api_key="test", call_fn=lambda p: CANNED_FOLLOWUP)
        result = await ar.propose(_mission(), _incomplete_report())
        assert result is not None
        # Should filter out docs.create (already completed) -> only web.research remains
        caps = [n.capability_id for n in result]
        assert "web.research" in caps
        assert "docs.create" not in caps  # not duplicated
    run(inner())


def test_adaptive_replan_respects_max_replan_limit():
    async def inner():
        net = CapabilityNetwork()
        ar = AdaptiveReplanner(net, PolicyEngine(net), PlanCritic(net),
                               api_key="test", call_fn=lambda p: CANNED_FOLLOWUP)
        # replan_count=2 -> blocked
        result = await ar.propose(_mission(replan_count=2), _incomplete_report())
        assert result is None
    run(inner())


def test_adaptive_replan_does_not_replan_when_complete():
    async def inner():
        net = CapabilityNetwork()
        ar = AdaptiveReplanner(net, PolicyEngine(net), PlanCritic(net),
                               api_key="test", call_fn=lambda p: CANNED_FOLLOWUP)
        complete_report = SemanticVerificationReport(complete=True, deliverables=[])
        result = await ar.propose(_mission(), complete_report)
        assert result is None
    run(inner())


def test_adaptive_replan_no_api_key_returns_none():
    async def inner():
        import os
        os.environ.pop("GEMINI_API_KEY", None)
        net = CapabilityNetwork()
        ar = AdaptiveReplanner(net, PolicyEngine(net), PlanCritic(net))
        result = await ar.propose(_mission(), _incomplete_report())
        # No LLM -> no replan (deterministic recovery handles individual failures)
        assert result is None
    run(inner())


def test_adaptive_replan_critic_rejection_blocks():
    async def inner():
        # A plan that the critic would reject (e.g. empty goal context)
        canned = '{"nodes": [{"capability_id": "unknown.thing", "depends_on": []}]}'
        net = CapabilityNetwork()
        ar = AdaptiveReplanner(net, PolicyEngine(net), PlanCritic(net),
                               api_key="test", call_fn=lambda p: canned)
        result = await ar.propose(_mission(), _incomplete_report())
        # unknown capability -> filtered out -> empty plan -> None
        assert result is None
    run(inner())


def test_adaptive_replan_empty_llm_response():
    async def inner():
        net = CapabilityNetwork()
        ar = AdaptiveReplanner(net, PolicyEngine(net), PlanCritic(net),
                               api_key="test", call_fn=lambda p: CANNED_EMPTY)
        result = await ar.propose(_mission(), _incomplete_report())
        assert result is None
    run(inner())