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
from nexora.core.personas import persona_for_capability


class LLMWorkflowCompiler:
    def __init__(self, network: CapabilityNetwork, router: ModelRouter,
                 api_key: Optional[str] = None, call_fn: Optional[Callable[[str], str]] = None):
        self.network = network
        self.router = router
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.call_fn = call_fn   # test seam: inject canned LLM text

    async def compile(self, goal: str, intent: MissionIntent,
                      constitution: MissionConstitution,
                      attachment=None, context_bundle=None,
                      outcome_contract=None) -> Optional[List[MissionNode]]:
        if not self.api_key and not self.call_fn:
            return None                      # deterministic fallback path
        try:
            text = await self._call(self._prompt(goal, constitution, context_bundle, outcome_contract))
        except Exception:
            return None                      # model outage -> fallback, never crash
        return self.parse_plan(text, constitution, intent, attachment,
                               context_bundle, outcome_contract)

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

    def _prompt(self, goal: str, constitution: MissionConstitution,
                context_bundle=None, outcome_contract=None) -> str:
        catalog = "\n".join(
            f"- {cid}: {self.network.get(cid).description}"
            for cid in constitution.allowed_capabilities if self.network.get(cid))

        context_section = ""
        if context_bundle and hasattr(context_bundle, "to_human_summary"):
            context_section = f"\nEXISTING CONTEXT:\n{context_bundle.to_human_summary()}\n"

        research_hint = ""
        if outcome_contract and getattr(outcome_contract, "needs_external_research", False):
            research_hint = ("\nIMPORTANT: This mission requires external web research. "
                              "Include a web.research node early in the plan so downstream "
                              "synthesis nodes can consume its findings.\n")

        return (f"You are NEXORA's workflow compiler.\nUSER GOAL: {goal}\n"
                f"CAPABILITY CATALOG:\n{catalog}\n"
                f"{context_section}{research_hint}"
                "Return ONLY JSON: {\"nodes\":[{\"capability_id\":\"...\",\"depends_on\":[\"capability_id\",...]}]}.\n"
                "Rules: use only catalog ids; research/search capabilities before synthesis ones; minimal plan."
                " If existing context is available, prefer reading it over creating generic documents.")

    # ---- deterministic validation + two-pass wiring (ADR-048) ----
    def parse_plan(self, text: str, constitution: MissionConstitution,
                   intent: MissionIntent, attachment=None,
                   context_bundle=None, outcome_contract=None) -> Optional[List[MissionNode]]:
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

            # Phase 6: Assign persona based on capability (ADR-058)
            persona = persona_for_capability(cid)

            n = MissionNode(capability_id=cid,
                            inputs=WorkflowCompiler._default_inputs(cid, intent, None),
                            rationale_summary=f"LLM-compiled: {cid} [{persona.role}]",
                            persona=persona.role)
            # Phase 4: inject web.research-specific inputs
            if cid == "web.research":
                n.inputs["objective"] = intent.objective
                n.inputs["max_results"] = 5
            by_cap.setdefault(cid, n)
            nodes.append(n)
            specs.append((n, item.get("depends_on", [])))

        if attachment and "multimodal.analyze" not in by_cap \
           and "multimodal.analyze" in constitution.allowed_capabilities:
            # Phase 6: Assign persona to injected multimodal node
            persona = persona_for_capability("multimodal.analyze")
            n = MissionNode(capability_id="multimodal.analyze",
                            inputs={"attachment": attachment},
                            rationale_summary=f"LLM-compiled: attachment analysis [{persona.role}]",
                            persona=persona.role)
            by_cap["multimodal.analyze"] = n
            nodes.append(n)
            specs.append((n, []))

        # Phase 3: context-driven drive.read injection (if LLM didn't already add it)
        if (context_bundle and hasattr(context_bundle, "drive_items") and context_bundle.drive_items
                and "drive.read" not in by_cap
                and "drive.read" in constitution.allowed_capabilities):
            # Phase 6: Assign persona to injected drive.read node
            persona = persona_for_capability("drive.read")
            n = MissionNode(capability_id="drive.read",
                            inputs={"file_id": context_bundle.drive_items[0].resource_id,
                                    "title": context_bundle.drive_items[0].title},
                            rationale_summary=f"LLM-compiled: context discovery read [{persona.role}]",
                            persona=persona.role)
            by_cap["drive.read"] = n
            nodes.append(n)
            specs.append((n, []))

        # Phase 4: enforce web.research if contract requires it and LLM didn't add it
        if (outcome_contract and getattr(outcome_contract, "needs_external_research", False)
                and "web.research" not in by_cap
                and "web.research" in constitution.allowed_capabilities):
            # Phase 6: Assign persona to injected web.research node
            persona = persona_for_capability("web.research")
            n = MissionNode(capability_id="web.research",
                            inputs={"objective": intent.objective, "max_results": 5},
                            rationale_summary=f"LLM-compiled: contract-required web research [{persona.role}]",
                            persona=persona.role)
            by_cap["web.research"] = n
            nodes.append(n)
            specs.append((n, []))

        # Pass 2: capability ids -> real node UUIDs (never store capability strings)
        for node, dep_caps in specs:
            node.depends_on = [by_cap[c].node_id for c in dep_caps
                               if c in by_cap and by_cap[c].node_id != node.node_id]
        return nodes or None