"""Semantic Verification — contract-aware outcome checking (ADR-054).

Replaces "all nodes succeeded = mission complete" with a contract-aware check:
does each required deliverable actually exist and satisfy its success criteria?

The verifier is layered ON TOP OF the existing structural verification — it never
weakens safety. It runs after structural verification passes.

Two modes:
- With Gemini API key: LLM-driven semantic check (reads artifact content)
- Without: deterministic structural fallback (artifact count vs deliverable count)

The output feeds the replan loop in Phase 5: missing/partial deliverables trigger
constrained replanning.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field


class DeliverableStatus(str):
    SATISFIED = "SATISFIED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"


class DeliverableCheck(BaseModel):
    name: str
    status: str          # SATISFIED | PARTIAL | MISSING
    reason: str = ""
    artifact_ids: List[str] = []


class SemanticVerificationReport(BaseModel):
    complete: bool = False
    deliverables: List[DeliverableCheck] = []
    evidence_status: str = "UNKNOWN"   # SUFFICIENT | INSUFFICIENT | UNKNOWN
    missing_requirements: List[str] = []
    recommended_next_actions: List[str] = []
    rationale: str = ""


VERIFY_PROMPT = """You are NEXORA's Semantic Verifier. You check whether mission
deliverables satisfy the Outcome Contract.

OUTCOME CONTRACT:
{contract_json}

PRODUCED ARTIFACTS (type, title/rationale, content excerpt):
{artifacts_summary}

COLLECTED EVIDENCE (claims with sources):
{evidence_summary}

For each required_deliverable in the contract, determine:
- SATISFIED: the deliverable exists and meets its success criteria
- PARTIAL: the deliverable exists but is incomplete or insufficient
- MISSING: no deliverable matches this requirement

Also determine evidence_status:
- SUFFICIENT: required_evidence items have been collected
- INSUFFICIENT: some required evidence is missing
- UNKNOWN: cannot determine

Return ONLY valid JSON matching this schema:
{{
  "deliverables": [
    {{"name": "deliverable name", "status": "SATISFIED|PARTIAL|MISSING",
      "reason": "why", "artifact_ids": ["id1"]}},
    ...
  ],
  "evidence_status": "SUFFICIENT|INSUFFICIENT|UNKNOWN",
  "recommended_next_actions": ["action 1", "action 2"]
}}

Rules:
- Be strict: if a deliverable is genuinely incomplete, say PARTIAL, not SATISFIED.
- recommended_next_actions should be concrete (e.g. "Research 2 more competitors").
- Keep reasons concise (one sentence).
"""


class SemanticVerifier:
    """Contract-aware outcome verification with LLM + deterministic fallback."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 call_fn=None):
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("NEXORA_MODEL_T2", "gemini-2.0-flash")
        self.call_fn = call_fn

    async def verify(self, contract, artifacts: List, evidence: List,
                     receipts: List) -> SemanticVerificationReport:
        """Run semantic verification. Never raises — degrades to structural fallback."""
        try:
            if not self.api_key and not self.call_fn:
                return self._structural_fallback(contract, artifacts)

            summary = self._build_artifacts_summary(artifacts, receipts)
            ev_summary = self._build_evidence_summary(evidence)
            contract_json = self._serialize_contract(contract)

            prompt = VERIFY_PROMPT.format(
                contract_json=contract_json,
                artifacts_summary=summary,
                evidence_summary=ev_summary,
            )
            text = await self._call(prompt)
            parsed = self._parse(text)
            if parsed is None:
                return self._structural_fallback(contract, artifacts)

            deliverables = [
                DeliverableCheck(
                    name=d.get("name", "?"),
                    status=d.get("status", "MISSING"),
                    reason=d.get("reason", ""),
                    artifact_ids=d.get("artifact_ids", []),
                )
                for d in parsed.get("deliverables", [])
            ]
            complete = all(d.status == DeliverableStatus.SATISFIED for d in deliverables)
            missing = [d.name for d in deliverables if d.status == DeliverableStatus.MISSING]
            partial = [d.name for d in deliverables if d.status == DeliverableStatus.PARTIAL]
            rationale_parts = []
            if missing:
                rationale_parts.append(f"{len(missing)} missing deliverable(s)")
            if partial:
                rationale_parts.append(f"{len(partial)} partial deliverable(s)")
            if not missing and not partial:
                rationale_parts.append("All deliverables satisfied")

            return SemanticVerificationReport(
                complete=complete,
                deliverables=deliverables,
                evidence_status=parsed.get("evidence_status", "UNKNOWN"),
                missing_requirements=missing,
                recommended_next_actions=parsed.get("recommended_next_actions", []),
                rationale="; ".join(rationale_parts),
            )
        except Exception as e:
            return self._structural_fallback(contract, artifacts, error=str(e))

    async def _call(self, prompt: str) -> str:
        if self.call_fn:
            return self.call_fn(prompt)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, headers={"x-goog-api-key": self.api_key},
                             json={"contents": [{"parts": [{"text": prompt}]}],
                                   "generationConfig": {"temperature": 0.1}})
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _serialize_contract(self, contract) -> str:
        if hasattr(contract, "model_dump"):
            return json.dumps(contract.model_dump(mode="json"), indent=2)
        return json.dumps(contract, indent=2)

    def _build_artifacts_summary(self, artifacts, receipts) -> str:
        if not artifacts:
            return "(no artifacts produced)"
        lines = []
        for a in artifacts:
            title = getattr(a, "type", "?")
            uri = getattr(a, "uri", "")
            # Find the receipt for rationale
            receipt = next((r for r in receipts if getattr(r, "output_artifact_id", None) == getattr(a, "artifact_id", None)), None)
            rationale = getattr(receipt, "reason", "") if receipt else ""
            lines.append(f"- {title} ({getattr(a, 'artifact_id', '?')[:8]}): {rationale or uri}")
        return "\n".join(lines)

    def _build_evidence_summary(self, evidence) -> str:
        if not evidence:
            return "(no evidence collected)"
        lines = []
        for e in evidence:
            claim = getattr(e, "claim", "")
            sources = getattr(e, "sources", [])
            lines.append(f"- {claim} (sources: {len(sources)})")
        return "\n".join(lines)

    def _parse(self, text: str) -> Optional[Dict[str, Any]]:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

    def _structural_fallback(self, contract, artifacts,
                             error: Optional[str] = None) -> SemanticVerificationReport:
        """Deterministic fallback when LLM is unavailable.
        Uses artifact count as a coarse proxy for deliverable coverage."""
        required = getattr(contract, "required_deliverables", []) or []
        n_required = len(required)
        n_artifacts = len(artifacts) if artifacts else 0

        deliverables: List[DeliverableCheck] = []
        for name in required:
            # Very coarse: mark SATISFIED only if we have more artifacts than required
            status = (DeliverableStatus.SATISFIED
                      if n_artifacts >= n_required
                      else DeliverableStatus.PARTIAL if n_artifacts > 0
                      else DeliverableStatus.MISSING)
            deliverables.append(DeliverableCheck(
                name=name, status=status,
                reason="(structural fallback — semantic check unavailable)",
            ))

        complete = all(d.status == DeliverableStatus.SATISFIED for d in deliverables)
        missing = [d.name for d in deliverables if d.status == DeliverableStatus.MISSING]
        rationale = (f"Structural fallback: {n_artifacts} artifacts vs {n_required} deliverables."
                     + (f" Error: {error}" if error else ""))
        return SemanticVerificationReport(
            complete=complete,
            deliverables=deliverables,
            evidence_status="UNKNOWN",
            missing_requirements=missing,
            recommended_next_actions=[],
            rationale=rationale,
        )