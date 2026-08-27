"""Adaptive Replanning — contract-aware follow-up plans (ADR-057).

When semantic verification reports missing/partial deliverables, this module
proposes a constrained follow-up plan (max 3 new nodes, max 2 cycles).

CRITICAL safety boundaries:
- Cannot remove completed work
- Cannot weaken policy
- Must pass Plan Critic
- Must pass Policy Engine
- Must respect mission constraints + approval policy
- Only affects pending/failed/incomplete work

Deterministic recovery (existing Replanner) handles individual node failures.
This handles contract-level incompleteness after full execution.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from packages.core.models import MissionNode, MissionIntent, MissionConstitution
from nexora.core.capability_network import CapabilityNetwork
from nexora.core.policy_engine import PolicyEngine
from nexora.agents.critic import PlanCritic


REPLAN_PROMPT = """You are NEXORA's Adaptive Replanner.

The mission ran its initial plan but semantic verification found the outcome is
not yet complete. You must propose a SMALL follow-up plan (max {max_nodes} new nodes)
that addresses the gaps.

ORIGINAL GOAL:
{goal}

CURRENT MISSION STATE:
- Completed nodes: {completed_caps}
- Failed nodes: {failed_caps}
- Artifacts produced: {artifact_types}

SEMANTIC VERIFICATION REPORT:
- Missing requirements: {missing}
- Partial deliverables: {partial}
- Recommended next actions: {recommended}

AVAILABLE CAPABILITIES:
{catalog}

Return ONLY valid JSON matching this schema:
{{
  "nodes": [
    {{"capability_id": "...", "depends_on": ["capability_id", ...],
      "rationale": "why this node closes the gap"}}
  ]
}}

Rules:
- MAXIMUM {max_nodes} new nodes.
- Use ONLY capabilities from the catalog.
- Research/search before synthesis (depends_on should reference existing or new research caps).
- Do NOT duplicate already-completed work.
- If no follow-up can close the gaps (e.g. missing external data that can't be gathered),
  return {{"nodes": []}} with a "reason" field explaining why.
"""


class AdaptiveReplanner:
    """Constrained LLM-based replanning for contract-level incompleteness."""

    def __init__(self, network: CapabilityNetwork, policy: PolicyEngine,
                 critic: PlanCritic,
                 api_key: Optional[str] = None, model: Optional[str] = None,
                 call_fn=None):
        self.network = network
        self.policy = policy
        self.critic = critic
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("NEXORA_MODEL_T2", "gemini-2.0-flash")
        self.call_fn = call_fn   # test seam

    async def propose(self, mission, semantic_report,
                      max_new_nodes: int = 3) -> Optional[List[MissionNode]]:
        """Propose a validated follow-up plan, or None if replanning is blocked."""
        # Hard constraints
        if not semantic_report or getattr(semantic_report, "complete", True):
            return None
        if mission.replan_count >= 2:
            return None  # max replan cycles reached (demo limit)

        missing = getattr(semantic_report, "missing_requirements", []) or []
        recommended = getattr(semantic_report, "recommended_next_actions", []) or []
        if not missing and not recommended:
            return None

        # Collect current state for the LLM
        completed_caps = sorted({n.capability_id for n in mission.nodes if n.status == "SUCCESS"})
        failed_caps = sorted({n.capability_id for n in mission.nodes if n.status == "FAILED"})
        artifact_types = sorted({a.type for a in mission.artifacts})

        try:
            llm_nodes = await self._call_llm(
                mission.goal, completed_caps, failed_caps, artifact_types,
                missing, recommended, mission.constitution, max_new_nodes)
        except Exception:
            return None

        if not llm_nodes:
            return None

        # Build fresh nodes with new UUIDs
        new_nodes = []
        id_map = {n.capability_id: n.node_id for n in mission.nodes}
        for spec in llm_nodes:
            cid = spec.get("capability_id")
            if not cid or not self.network.get(cid):
                continue
            if cid in mission.constitution.forbidden_actions:
                continue
            # Don't duplicate already-completed work
            if cid in completed_caps:
                continue
            n = MissionNode(
                capability_id=cid,
                depends_on=[id_map[d] for d in spec.get("depends_on", [])
                            if d in id_map],
                inputs=self._default_inputs(cid, mission.intent),
                rationale_summary=f"Replan: {spec.get('rationale', '')[:100]}",
            )
            new_nodes.append(n)
            id_map[cid] = n.node_id

        if not new_nodes:
            return None

        # Cap at max_new_nodes
        new_nodes = new_nodes[:max_new_nodes]

        # Validate through critic + policy
        if not await self._validate(new_nodes, mission):
            return None

        return new_nodes

    async def _call_llm(self, goal, completed, failed, artifacts,
                        missing, recommended, constitution, max_nodes) -> List[Dict]:
        catalog = "\n".join(
            f"- {cid}: {self.network.get(cid).description}"
            for cid in constitution.allowed_capabilities if self.network.get(cid))

        prompt = REPLAN_PROMPT.format(
            max_nodes=max_nodes,
            goal=goal,
            completed_caps=", ".join(completed) or "(none)",
            failed_caps=", ".join(failed) or "(none)",
            artifact_types=", ".join(artifacts) or "(none)",
            missing="\n".join(f"- {m}" for m in missing) or "(none)",
            partial="(see recommended actions)",
            recommended="\n".join(f"- {r}" for r in recommended) or "(none)",
            catalog=catalog,
        )

        if self.call_fn:
            text = self.call_fn(prompt)
        else:
            text = await self._call_gemini(prompt)

        return self._parse(text)

    async def _call_gemini(self, prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError("No Gemini API key")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, headers={"x-goog-api-key": self.api_key},
                             json={"contents": [{"parts": [{"text": prompt}]}],
                                   "generationConfig": {"temperature": 0.2}})
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _parse(self, text: str) -> List[Dict]:
        m = re.search(r"\{.*\}", text, re.S) or re.search(r"\[.*\]", text, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except Exception:
            return []
        raw = data.get("nodes") if isinstance(data, dict) else data
        return raw if isinstance(raw, list) else []

    async def _validate(self, nodes: List[MissionNode], mission) -> bool:
        """Run critic + policy check. Reject if either fails."""
        try:
            critique = await self.critic.critique(nodes, mission.constitution)
            if not critique["approved"]:
                return False
        except Exception:
            return False

        for n in nodes:
            cap = self.network.get(n.capability_id)
            decision = self.policy.evaluate(n.capability_id, mission.constitution,
                                            cap, extra_params=n.inputs)
            if decision == "BLOCK":
                return False
        return True

    @staticmethod
    def _default_inputs(cap_id: str, intent) -> dict:
        from nexora.core.compiler import WorkflowCompiler
        # Reuse the compiler's input defaults — DRY
        return WorkflowCompiler._default_inputs(cap_id, intent, None)