import asyncio
from nexora.core.contract import ContractGenerator, OutcomeContract

def run(c): return asyncio.run(c)


CANNED_GHOST = '''
{
  "objective": "Evaluate commercial viability of Ghost Run and prepare a launch recommendation.",
  "success_criteria": [
    "Market size and trends are documented with citations",
    "At least 3 direct competitors analyzed",
    "Revenue scenarios include conservative/base/optimistic cases",
    "Risk assessment covers technical and market risks",
    "Clear go/no-go recommendation with rationale"
  ],
  "required_deliverables": [
    "Market research document",
    "Competitor analysis",
    "Financial model spreadsheet",
    "Risk assessment",
    "Launch recommendation",
    "Executive summary",
    "Executive presentation deck"
  ],
  "required_evidence": [
    "Mobile gaming market data",
    "Comparable ghost-mechanic games",
    "Monetization benchmarks",
    "Any existing Ghost Run project context"
  ],
  "constraints": [
    "No external communication without approval",
    "Cite all external research sources"
  ],
  "needs_external_research": true
}
'''


def test_contract_generation_with_canned_llm():
    async def inner():
        gen = ContractGenerator(api_key="test", call_fn=lambda p: CANNED_GHOST)
        c = await gen.generate("Evaluate whether Ghost Run can succeed commercially")
        assert isinstance(c, OutcomeContract)
        assert c.needs_external_research is True
        assert "Financial model spreadsheet" in c.required_deliverables
        assert len(c.success_criteria) >= 3
    run(inner())


def test_contract_malformed_output_falls_back():
    async def inner():
        gen = ContractGenerator(api_key="test", call_fn=lambda p: "not json at all {{{")
        c = await gen.generate("Schedule a meeting")
        assert isinstance(c, OutcomeContract)
        assert c.objective == "Schedule a meeting"
    run(inner())


def test_contract_no_api_key_uses_minimal():
    async def inner():
        import os
        os.environ.pop("GEMINI_API_KEY", None)
        gen = ContractGenerator()
        c = await gen.generate("Prepare investor pitch")
        assert isinstance(c, OutcomeContract)
        assert c.objective == "Prepare investor pitch"
        assert c.approval_policy == "default"
    run(inner())


def test_contract_rejects_unexpected_fields():
    """Pydantic must ignore unknown fields from LLM output."""
    async def inner():
        extra = CANNED_GHOST.replace('}', ', "made_up_field": 42}')
        gen = ContractGenerator(api_key="test", call_fn=lambda p: extra)
        # Pydantic v2 default: extra fields ignored unless forbid
        c = await gen.generate("x")
        assert isinstance(c, OutcomeContract)
    run(inner())