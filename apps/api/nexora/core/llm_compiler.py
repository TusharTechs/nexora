"""LLM Workflow Compiler (ADR-051).

Natural goal -> Gemini-compiled capability plan. The LLM output is UNTRUSTED:
every capability is validated against the Capability Network and Constitution.
If no API key is configured (or the call fails), returns None and the caller
falls back to the deterministic keyword compiler. Never hard-depends on a model.
"""
import json
import os
import re
from typing import Callable, List, Optional

from packages.core.models import MissionNode, MissionIntent, MissionConstitution
from nexora.core.capability_network import CapabilityNetwork
from nexora.core.model_router import ModelRouter, ModelTier
from nexora.core.compiler import WorkflowCompiler


class LLMWorkflowCompiler:
    def __init__(self, network: CapabilityNetwork, router: ModelRouter,
                 api_key: Optional[str] = None, call_fn: Optional[Callable[[str], str]] = None):
        self.network = network
        self.router = router
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.call_fn = call_fn   # test seam: inject canned LLM text

    async def compile(self, goal: str, intent: MissionIntent,
                      constitution: MissionConstitution,
                      attachment=None) -> Optional[List[MissionNode]]:
        if not self.api_key and not self.call_fn:
            return None                      # deterministic fallback path
        try:
            text = await self._call(self._prompt(goal, constitution))
        except Exception:
            return None                      # model outage -> fallback, never crash
        return self.parse_plan(text, constitution, intent, attachment)

    async def _call(self, prompt: str) -> str:
        if self.call_fn:
            return self.call_fn(prompt)
        import httpx
        model = self.router.route(ModelTier.T2) or os.getenv("NEXORA_MODEL_DEFAULT", "gemini-2.0-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, headers={"x-goog-api-key": self.api_key},
                             json={"contents": [{"parts": [{"text": prompt}]}],
                                   "generationConfig": {"temperature": 0.2}})
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _prompt(self, goal: str, constitution: MissionConstitution) -> str:
        catalog = "\n".join(
            f"- {cid}: {self.network.get(cid).description}"
            for cid in constitution.allowed_capabilities if self.network.get(cid))
        return (f"You are NEXORA's workflow compiler.\nUSER GOAL: {goal}\n"
                f"CAPABILITY CATALOG:\n{catalog}\n"
                "Return ONLY JSON: {\"nodes\":[{\"capability_id\":\"...\",\"depends_on\":[\"capability_id\",...]}]}.\n"
                "Rules: use only catalog ids; research/search capabilities before synthesis ones; minimal plan.")

    # ---- deterministic validation + two-pass wiring (ADR-048) ----
    def parse_plan(self, text: str, constitution: MissionConstitution,
                   intent: MissionIntent, attachment=None) -> Optional[List[MissionNode]]:
        m = re.search(r"\{.*\}", text, re.S) or re.search(r"\[.*\]", text, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None
        raw = data.get("nodes") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            return None

        specs, nodes, by_cap = [], [], {}
        for item in raw:
            cid = item.get("capability_id")
            if not cid or not self.network.get(cid):
                continue                                   # unknown capability -> drop
            if cid not in constitution.allowed_capabilities:
                continue                                   # not allowed -> drop
            if cid in constitution.forbidden_actions:
                continue                                   # forbidden -> drop
            n = MissionNode(capability_id=cid,
                            inputs=WorkflowCompiler._default_inputs(cid, intent, None),
                            rationale_summary=f"LLM-compiled: {cid}")
            by_cap.setdefault(cid, n)
            nodes.append(n)
            specs.append((n, item.get("depends_on", [])))

        if attachment and "multimodal.analyze" not in by_cap \
           and "multimodal.analyze" in constitution.allowed_capabilities:
            n = MissionNode(capability_id="multimodal.analyze",
                            inputs={"attachment": attachment},
                            rationale_summary="LLM-compiled: attachment analysis")
            by_cap["multimodal.analyze"] = n
            nodes.append(n)
            specs.append((n, []))

        # Pass 2: capability ids -> real node UUIDs (never store capability strings)
        for node, dep_caps in specs:
            node.depends_on = [by_cap[c].node_id for c in dep_caps
                               if c in by_cap and by_cap[c].node_id != node.node_id]
        return nodes or None