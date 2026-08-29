"""LLM Workflow Compiler (ADR-051, ADR-060).

Natural goal -> Gemini-compiled capability plan via the Unified LLM Client.
The LLM output is UNTRUSTED: every capability is validated against the
Capability Network and Constitution. If no LLM backend is configured (or the
call fails), returns None and the caller falls back to the deterministic
keyword compiler. Never hard-depends on a single backend.
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
        self.call_fn = call_fn

    async def compile(self, goal: str, intent: MissionIntent,
                      constitution: MissionConstitution,
                      attachment=None, context_bundle=None,
                      outcome_contract=None) -> Optional[List[MissionNode]]:
        from nexora.core.llm_client import llm_available
        if not self.call_fn and not llm_available():
            return None
        try:
            text = await self._call(self._prompt(goal, constitution, context_bundle, outcome_contract))
        except Exception:
            return None
        nodes = self.parse_plan(text, constitution, intent, attachment,
                                context_bundle, outcome_contract)
        nodes = self._dedupe_refinements(nodes)
        # Phase 9 hardening: guarantee a synthesis artifact for summary/report goals
        nodes = self._ensure_synthesis(goal, intent, constitution, attachment, nodes)
        # ADR-066: guarantee every required deliverable maps to a capability
        nodes = self._ensure_contract_coverage(intent, constitution, outcome_contract, nodes)
        return self._dedupe_refinements(nodes)

    @staticmethod
    def _dedupe_refinements(nodes):
        """Drop refinement ops that duplicate a create in the same plan
        (sheets.write after sheets.create, docs.update after docs.create with no
        distinct target)."""
        if not nodes:
            return nodes
        caps = {n.capability_id for n in nodes}
        drop = set()
        if "sheets.create" in caps and "sheets.write" in caps:
            drop.add("sheets.write")
        if "docs.create" in caps and "docs.update" in caps:
            drop.add("docs.update")
        if not drop:
            return nodes
        kept_ids = {n.node_id for n in nodes if n.capability_id not in drop}
        out = []
        for n in nodes:
            if n.capability_id in drop:
                continue
            n.depends_on = [d for d in n.depends_on if d in kept_ids]
            out.append(n)
        return out

    _ARCHITECT_INSTRUCTION = (
        "You are NEXORA's Mission Architect — a planning agent. You decompose a "
        "goal into the minimal ordered set of capability calls that will satisfy "
        "its Outcome Contract, always putting research/search before synthesis. "
        "You output only the requested JSON.")

    async def _call(self, prompt: str) -> str:
        if self.call_fn:
            return self.call_fn(prompt)
        from nexora.core.adk_runtime import try_run_agent
        adk = await try_run_agent(role="Mission Architect",
                                  instruction=self._ARCHITECT_INSTRUCTION, task=prompt)
        if adk and adk.strip():
            return adk
        from nexora.core.llm_client import llm_generate
        model = self.router.route(ModelTier.T2) or os.getenv("NEXORA_MODEL_DEFAULT", "gemini-3.5-flash")
        return await llm_generate(prompt, temperature=0.2, model=model)

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

        contract_section = ""
        if outcome_contract and getattr(outcome_contract, "required_deliverables", None):
            contract_section = ("\nREQUIRED DELIVERABLES (from Outcome Contract):\n" +
                                "\n".join(f"- {d}" for d in outcome_contract.required_deliverables) + "\n")

        advisory_hint = ""
        goal_lower = goal.lower()
        if any(word in goal_lower for word in ["learn", "study", "course", "curriculum"]):
            advisory_hint = ("\nThis is an ADVISORY goal (learning/education). "
                              "Produce a researched learning plan: use web.research to find "
                              "current resources, then docs.create to write a structured curriculum.\n")
        elif any(word in goal_lower for word in ["career", "job", "interview", "promotion"]):
            advisory_hint = ("\nThis is an ADVISORY goal (career growth). "
                              "Produce an actionable career plan: use web.research to find "
                              "industry insights, then docs.create to write a skill development roadmap.\n")
        elif any(word in goal_lower for word in ["budget", "finance", "save", "invest"]):
            advisory_hint = ("\nThis is an ADVISORY goal (personal finance). "
                              "Produce a researched financial plan: use web.research to find "
                              "current strategies, then sheets.create to build a budget tracker.\n")
        elif any(word in goal_lower for word in ["rich", "wealth", "money"]):
            advisory_hint = ("\nThis is a VAGUE ADVISORY goal. "
                              "Produce a researched, honest plan: use web.research to find "
                              "evidence-based wealth strategies, then docs.create to write a "
                              "realistic action plan. Be honest about limitations.\n")
        # Phase 10: Travel/visual/creative goals need images
        elif any(word in goal_lower for word in ["travel", "island", "beach", "vacation",
                                                 "trip", "visit", "recommend", "photo", "picture"]):
            advisory_hint = ("\nThis is a TRAVEL/RECOMMENDATION/VISUAL goal. "
                              "Include web.research for evidence-based recommendations, "
                              "docs.create for the written guide, AND imagen.generate_image "
                              "to produce inspiring visuals for the recommendation.\n")

        # Phase 11: Audio/briefing/podcast goals
        elif any(word in goal_lower for word in ["audio briefing", "audio narration", "podcast", "voiceover", "spoken",
                                                 "narration", "read aloud", "audio version"]):
            advisory_hint = ("\nThis is an AUDIO/BRIEFING goal. "
                              "Include web.research for evidence gathering, "
                              "docs.create for a written script, AND lyria.generate_audio "
                              "to produce an audio narration/briefing of the findings.\n")

        # Phase 9: explicitly hint summary/report goals need docs.create
        summary_hint = ""
        if any(w in goal_lower for w in ["summary", "summarize", "report", "brief"]):
            summary_hint = ("\nThis goal requests a SUMMARY/REPORT. You MUST include a docs.create node "
                             "at the end of the plan (depending on any search/research nodes) so the user "
                             "receives a real document artifact.\n")

        return (f"You are NEXORA's workflow compiler.\nUSER GOAL: {goal}\n"
                f"CAPABILITY CATALOG:\n{catalog}\n"
                f"{context_section}{contract_section}{research_hint}{advisory_hint}{summary_hint}"
                "Return ONLY JSON: {\"nodes\":[{\"capability_id\":\"...\",\"depends_on\":[\"capability_id\",...]}]}.\n"
                "Rules: use only catalog ids; research/search capabilities before synthesis ones; minimal plan."
                " If existing context is available, prefer reading it over creating generic documents."
                " For advisory goals, always include web.research for evidence gathering.")

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
                continue
            if cid not in constitution.allowed_capabilities:
                continue
            if cid in constitution.forbidden_actions:
                continue

            persona = persona_for_capability(cid)
            n = MissionNode(capability_id=cid,
                            inputs=WorkflowCompiler._default_inputs(cid, intent, None),
                            rationale_summary=f"LLM-compiled: {cid} [{persona.role}]",
                            persona=persona.role)
            if cid == "web.research":
                n.inputs["objective"] = intent.objective
                n.inputs["max_results"] = 5
            by_cap.setdefault(cid, n)
            nodes.append(n)
            specs.append((n, item.get("depends_on", [])))

        if attachment and "multimodal.analyze" not in by_cap \
           and "multimodal.analyze" in constitution.allowed_capabilities:
            persona = persona_for_capability("multimodal.analyze")
            n = MissionNode(capability_id="multimodal.analyze",
                            inputs={"attachment": attachment},
                            rationale_summary=f"LLM-compiled: attachment analysis [{persona.role}]",
                            persona=persona.role)
            by_cap["multimodal.analyze"] = n
            nodes.append(n)
            specs.append((n, []))

        if (context_bundle and hasattr(context_bundle, "drive_items") and context_bundle.drive_items
                and "drive.read" not in by_cap
                and "drive.read" in constitution.allowed_capabilities):
            persona = persona_for_capability("drive.read")
            n = MissionNode(capability_id="drive.read",
                            inputs={"file_id": context_bundle.drive_items[0].resource_id,
                                    "title": context_bundle.drive_items[0].title},
                            rationale_summary=f"LLM-compiled: context discovery read [{persona.role}]",
                            persona=persona.role)
            by_cap["drive.read"] = n
            nodes.append(n)
            specs.append((n, []))

        if (outcome_contract and getattr(outcome_contract, "needs_external_research", False)
                and "web.research" not in by_cap
                and "web.research" in constitution.allowed_capabilities):
            persona = persona_for_capability("web.research")
            n = MissionNode(capability_id="web.research",
                            inputs={"objective": intent.objective, "max_results": 5},
                            rationale_summary=f"LLM-compiled: contract-required web research [{persona.role}]",
                            persona=persona.role)
            by_cap["web.research"] = n
            nodes.append(n)
            specs.append((n, []))

        for node, dep_caps in specs:
            node.depends_on = [by_cap[c].node_id for c in dep_caps
                               if c in by_cap and by_cap[c].node_id != node.node_id]
        return nodes or None

    # Deliverable-noun -> capability. First match wins; order matters.
    _DELIVERABLE_CAP_RULES = [
        (("budget", "spreadsheet", "financial model", "tracker", "cost", "expense"), "sheets.create"),
        (("slide", "deck", "presentation", "pitch"), "slides.create"),
        (("image", "photo", "picture", "visual", "inspiration", "illustration", "moodboard"), "imagen.generate_image"),
        (("video", "clip", "trailer", "teaser"), "veo.generate_video"),
        (("audio briefing", "audio narration", "podcast", "voiceover", "spoken word"), "lyria.generate_audio"),
        (("task list", "action item", "to-do", "todo", "follow-up", "checklist"), "tasks.create"),
        (("meeting", "calendar", "kickoff", "schedule an"), "calendar.create_event"),
        (("email", "announcement", "outreach message"), "gmail.draft"),
        (("form", "survey", "questionnaire"), "forms.create"),
        (("document", "guide", "report", "plan", "roadmap", "summary", "brief",
          "analysis", "itinerary", "strategy", "curriculum", "playbook"), "docs.create"),
    ]

    def _ensure_contract_coverage(self, intent: MissionIntent,
                                  constitution: MissionConstitution,
                                  outcome_contract, nodes):
        if nodes is None or outcome_contract is None:
            return nodes
        deliverables = list(getattr(outcome_contract, "required_deliverables", []) or [])
        if not deliverables:
            return nodes
        have = {n.capability_id for n in nodes}
        research_ids = [n.node_id for n in nodes if n.capability_id in
                        {"gmail.search", "drive.search", "web.research", "drive.read",
                         "multimodal.analyze", "sheets.read", "people.search"}]
        for deliverable in deliverables:
            dl = deliverable.lower()
            cap = next((c for terms, c in self._DELIVERABLE_CAP_RULES
                        if any(t in dl for t in terms)), None)
            if not cap or cap in have or cap not in constitution.allowed_capabilities:
                continue
            if cap in constitution.forbidden_actions:
                continue
            persona = persona_for_capability(cap)
            inputs = WorkflowCompiler._default_inputs(cap, intent, None)
            if cap == "docs.create":
                inputs = {"title": deliverable[:90], "content": ""}
            n = MissionNode(capability_id=cap, inputs=inputs, depends_on=list(research_ids),
                            rationale_summary=f"Contract coverage: deliverable '{deliverable[:60]}' "
                                              f"→ {cap}. [{persona.role}]",
                            persona=persona.role)
            nodes.append(n)
            have.add(cap)
        return nodes

    def _ensure_synthesis(self, goal: str, intent: MissionIntent,
                          constitution: MissionConstitution, attachment,
                          nodes: Optional[List[MissionNode]]) -> Optional[List[MissionNode]]:
        """Phase 9: guarantee the plan produces an artifact for summary/report goals."""
        if nodes is None:
            return None

        goal_lower = goal.lower()
        wants_doc = any(w in goal_lower for w in
                        ["summary", "summarize", "report", "doc", "document", "brief",
                         "plan", "roadmap", "write", "create a"])
        has_doc = any(n.capability_id == "docs.create" for n in nodes)
        has_any_artifact = any(
            n.capability_id in {
                "docs.create", "sheets.create", "slides.create",
                "calendar.create_event", "tasks.create", "forms.create",
                "veo.generate_video", "lyria.generate_audio", "web.research",
                "multimodal.analyze", "imagen.generate_image"
            }
            for n in nodes
        )

        if wants_doc and not has_doc and not has_any_artifact \
                and "docs.create" in constitution.allowed_capabilities:
            research_ids = [n.node_id for n in nodes
                            if n.capability_id in {
                                "gmail.search", "drive.search", "web.research",
                                "gmail.read", "drive.read", "multimodal.analyze",
                                "sheets.read", "people.search"
                            }]
            persona = persona_for_capability("docs.create")
            nodes.append(MissionNode(
                capability_id="docs.create",
                inputs={
                    "title": f"Summary - {intent.objective[:80]}",
                    "content": "Summarize the upstream research and search results.",
                },
                depends_on=research_ids,
                rationale_summary=(f"Planner hardening: goal asks for a summary/document, "
                                  f"so added docs.create artifact. [{persona.role}]"),
                persona=persona.role,
            ))
        return nodes