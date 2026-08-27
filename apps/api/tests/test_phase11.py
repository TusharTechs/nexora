import asyncio
from nexora.core.contract import OutcomeContract
from nexora.core.semantic_verifier import SemanticVerifier, DeliverableStatus
from packages.core.models import Artifact, Evidence, ActionReceipt

def run(c): return asyncio.run(c)


def _contract(deliverables, evidence=None):
    return OutcomeContract(
        objective="test",
        success_criteria=["x"],
        required_deliverables=deliverables,
        required_evidence=evidence or [],
        constraints=[],
        needs_external_research=False,
    )


def _artifact(aid, atype):
    return Artifact(artifact_id=aid, mission_id="m", node_id="n",
                    type=atype, provider="mock", resource_id=aid, uri=f"mock://{aid}")


def _receipt(aid, reason):
    return ActionReceipt(mission_id="m", node_id="n", action="x", reason=reason,
                         agent_id="worker", capability_id="docs.create",
                         policy_decision="ALLOW", model_tier="T1",
                         output_artifact_id=aid, execution_mode="MOCK")


CANNED_ALL_SATISFIED = '''
{
  "deliverables": [
    {"name": "market research", "status": "SATISFIED",
     "reason": "Covers market size, trends, with citations", "artifact_ids": ["a1"]},
    {"name": "financial model", "status": "SATISFIED",
     "reason": "Revenue scenarios present", "artifact_ids": ["a2"]}
  ],
  "evidence_status": "SUFFICIENT",
  "recommended_next_actions": []
}
'''

CANNED_PARTIAL = '''
{
  "deliverables": [
    {"name": "market research", "status": "SATISFIED",
     "reason": "Covers market size", "artifact_ids": ["a1"]},
    {"name": "financial model", "status": "PARTIAL",
     "reason": "Revenue scenarios missing", "artifact_ids": ["a2"]}
  ],
  "evidence_status": "INSUFFICIENT",
  "recommended_next_actions": ["Add conservative/base/optimistic revenue scenarios"]
}
'''

CANNED_MISSING = '''
{
  "deliverables": [
    {"name": "market research", "status": "SATISFIED",
     "reason": "Present", "artifact_ids": ["a1"]},
    {"name": "financial model", "status": "MISSING",
     "reason": "No financial model artifact found", "artifact_ids": []}
  ],
  "evidence_status": "INSUFFICIENT",
  "recommended_next_actions": ["Create financial model spreadsheet"]
}
'''


def test_semantic_verify_all_satisfied():
    async def inner():
        v = SemanticVerifier(api_key="test", call_fn=lambda p: CANNED_ALL_SATISFIED)
        c = _contract(["market research", "financial model"])
        arts = [_artifact("a1", "DOC"), _artifact("a2", "SHEET")]
        recs = [_receipt("a1", "market research"), _receipt("a2", "financial model")]
        r = await v.verify(c, arts, [], recs)
        assert r.complete is True
        assert all(d.status == DeliverableStatus.SATISFIED for d in r.deliverables)
    run(inner())


def test_semantic_verify_partial():
    async def inner():
        v = SemanticVerifier(api_key="test", call_fn=lambda p: CANNED_PARTIAL)
        c = _contract(["market research", "financial model"])
        r = await v.verify(c, [_artifact("a1", "DOC"), _artifact("a2", "SHEET")],
                           [], [_receipt("a1", "x"), _receipt("a2", "x")])
        assert r.complete is False
        assert any(d.status == DeliverableStatus.PARTIAL for d in r.deliverables)
        assert len(r.recommended_next_actions) >= 1
    run(inner())


def test_semantic_verify_missing():
    async def inner():
        v = SemanticVerifier(api_key="test", call_fn=lambda p: CANNED_MISSING)
        c = _contract(["market research", "financial model"])
        r = await v.verify(c, [_artifact("a1", "DOC")], [], [_receipt("a1", "x")])
        assert r.complete is False
        assert "financial model" in r.missing_requirements
    run(inner())


def test_semantic_verify_no_api_key_uses_fallback():
    async def inner():
        import os
        os.environ.pop("GEMINI_API_KEY", None)
        v = SemanticVerifier()
        c = _contract(["d1", "d2"])
        # 2 artifacts, 2 deliverables -> fallback marks all SATISFIED
        r = await v.verify(c, [_artifact("a1", "DOC"), _artifact("a2", "DOC")], [], [])
        assert r.complete is True
        assert "Structural fallback" in r.rationale
    run(inner())


def test_semantic_verify_fallback_partial_when_artifacts_fewer():
    async def inner():
        import os
        os.environ.pop("GEMINI_API_KEY", None)
        v = SemanticVerifier()
        c = _contract(["d1", "d2", "d3"])
        # 1 artifact, 3 deliverables -> fallback marks PARTIAL
        r = await v.verify(c, [_artifact("a1", "DOC")], [], [])
        assert r.complete is False
        assert any(d.status == DeliverableStatus.PARTIAL for d in r.deliverables)
    run(inner())


def test_semantic_verify_malformed_llm_falls_back():
    async def inner():
        v = SemanticVerifier(api_key="test", call_fn=lambda p: "not json {{{")
        c = _contract(["d1", "d2"])
        r = await v.verify(c, [_artifact("a1", "DOC"), _artifact("a2", "DOC")], [], [])
        # Falls back to structural — should still produce a valid report
        assert r.complete in (True, False)
        assert "fallback" in r.rationale.lower()
    run(inner())