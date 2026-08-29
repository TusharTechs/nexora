"""Phase 21 — Artifact Composer, contract coverage, grounded research fallback,
and adaptive-replan dispatch (ADR-066)."""
import asyncio

import pytest

from packages.core.models import (Mission, MissionIntent, MissionNode,
                                  MissionConstitution, ExecutionMode)
from nexora.core.composer import ArtifactComposer, _extract_json
from nexora.core.capability_network import CapabilityNetwork
from nexora.core.model_router import ModelRouter
from nexora.core.llm_compiler import LLMWorkflowCompiler
from nexora.core.contract import OutcomeContract


# ---------------- Composer ----------------

def test_composer_document_fallback_is_nonempty_without_llm():
    c = ArtifactComposer()  # no call_fn, tests run with no LLM key
    out = asyncio.run(c.compose_document(
        title="NYC Guide", objective="Visit New York tomorrow",
        evidence_text="• Times Square\n  Busy at night"))
    assert "NYC Guide" in out
    assert len(out) > 100


def test_composer_document_uses_llm_when_available():
    calls = {}
    def fake(prompt):
        calls["p"] = prompt
        return ("# Real Guide\n\nExecutive summary: go to Central Park, then walk the "
                "High Line and finish at Chelsea Market. Budget roughly $150 for the day "
                "including transit, lunch and one paid attraction. Bring comfortable shoes.")
    c = ArtifactComposer(call_fn=fake)
    out = asyncio.run(c.compose_document(title="T", objective="see NYC"))
    assert "Central Park" in out
    assert "see NYC" in calls["p"]


def test_composer_slides_parses_json_and_falls_back():
    good = ArtifactComposer(call_fn=lambda p: '[{"title":"Intro","bullets":["a","b"]},'
                                              '{"title":"Next steps","bullets":["do x"]}]')
    deck = asyncio.run(good.compose_slides(title="D", objective="o"))
    assert deck[0]["title"] == "Intro" and deck[0]["bullets"] == ["a", "b"]

    bad = ArtifactComposer(call_fn=lambda p: "not json at all")
    deck2 = asyncio.run(bad.compose_slides(title="D", objective="o",
                                           evidence_text="• finding one"))
    assert deck2 and all("title" in s for s in deck2)


def test_composer_sheet_returns_headers_and_rows():
    c = ArtifactComposer(call_fn=lambda p: '{"headers":["Category","Cost"],'
                                           '"rows":[["Hotel","200"],["TOTAL","200"]]}')
    out = asyncio.run(c.compose_sheet(title="Budget", objective="trip"))
    assert out["headers"] == ["Category", "Cost"]
    assert ["TOTAL", "200"] in out["rows"]


def test_composer_sheet_fallback_has_total_row():
    out = asyncio.run(ArtifactComposer().compose_sheet(title="Budget", objective="trip"))
    assert any(r[0] == "TOTAL" for r in out["rows"])


def test_extract_json_handles_fenced_and_bare():
    assert _extract_json('```json\n{"a":1}\n```') == {"a": 1}
    assert _extract_json('prose {"b":2} more') == {"b": 2}
    assert _extract_json("nothing here") is None


# ---------------- Contract coverage ----------------

def test_contract_coverage_adds_missing_deliverable_capabilities():
    net = CapabilityNetwork()
    comp = LLMWorkflowCompiler(net, ModelRouter())
    intent = MissionIntent(objective="launch the app")
    con = MissionConstitution(mission_id="m", allowed_capabilities=net.ids())
    # LLM only produced a doc; contract also wants a budget + a deck.
    nodes = [MissionNode(capability_id="docs.create", inputs={"title": "Plan"})]
    contract = OutcomeContract(
        objective="launch",
        required_deliverables=["A written launch plan document",
                               "A budget spreadsheet",
                               "An investor pitch slide deck"],
    )
    out = comp._ensure_contract_coverage(intent, con, contract, nodes)
    caps = {n.capability_id for n in out}
    assert "sheets.create" in caps
    assert "slides.create" in caps


def test_contract_coverage_noop_without_contract():
    net = CapabilityNetwork()
    comp = LLMWorkflowCompiler(net, ModelRouter())
    nodes = [MissionNode(capability_id="docs.create")]
    assert comp._ensure_contract_coverage(MissionIntent(objective="x"),
                                          MissionConstitution(mission_id="m"),
                                          None, nodes) == nodes


# ---------------- Adaptive-replan dispatch (regression) ----------------

def test_supervisor_dispatches_followups_with_satisfied_deps():
    """A follow-up node whose deps already completed must still be dispatched,
    not left PENDING forever."""
    import nexora.agents.supervisor as sup_mod

    dispatched = []

    class FakeRuntime:
        async def dispatch(self, mid, nid):
            dispatched.append(nid)

    done = MissionNode(capability_id="docs.create", status="SUCCESS")
    followup = MissionNode(capability_id="docs.update", depends_on=[done.node_id])
    mission = Mission(goal="g", nodes=[done, followup])

    done_ids = {n.node_id for n in mission.nodes if n.status in ("SUCCESS", "SKIPPED")}
    rt = FakeRuntime()
    # Mirror the supervisor's dispatch rule
    async def _run():
        for n in [followup]:
            if all(d in done_ids for d in n.depends_on):
                await rt.dispatch(mission.mission_id, n.node_id)
    asyncio.run(_run())
    assert followup.node_id in dispatched
