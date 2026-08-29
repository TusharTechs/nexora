from typing import List, Optional, Tuple
from packages.core.models import MissionNode, MissionIntent, MissionConstitution, NodeCondition
from nexora.core.capability_network import CapabilityNetwork
from nexora.core.personas import persona_for_capability

KEYWORD_RULES: List[Tuple[Tuple[str, ...], str]] = [
    (("email", "gmail", "inbox", "customer sent"), "gmail.search"),
    (("drive", "file", "contract"), "drive.search"),
    (("sheet", "spreadsheet", "tracker", "budget"), "sheets.create"),
    (("impact",), "sheets.read"),
    (("meeting", "schedule", "sync", "calendar"), "calendar.create_event"),
    (("send",), "gmail.send"),
    (("report", "doc", "write", "brief"), "docs.create"),
    (("task",), "tasks.create"),
    (("screenshot", "image", "attachment"), "multimodal.analyze"),
    (("slides", "presentation", "deck"), "slides.create"),
    (("notify", "chat"), "chat.notify"),
    (("survey", "questionnaire"), "forms.create"),
    (("people", "contacts", "stakeholder"), "people.search"),
    (("video",), "veo.generate_video"),
    (("audio briefing", "audio narration", "podcast", "voiceover"), "lyria.generate_audio"),
    # Phase 10: Image generation for visual/travel/creative goals
    (("photo", "picture", "visual", "illustration", "island", "beach",
      "travel", "vacation", "destination", "trip"), "imagen.generate_image"),
]
RESEARCH_CAPS = {"gmail.search", "drive.search", "drive.read", "multimodal.analyze",
                 "sheets.read", "people.search", "web.research"}
# Phase 10: Added imagen.generate_image to synthesis capabilities
SYNTHESIS_CAPS = {"docs.create", "calendar.create_event", "gmail.send", "slides.create",
                  "chat.notify", "tasks.create", "forms.create",
                  "veo.generate_video", "lyria.generate_audio", "imagen.generate_image"}

# Phase 8B: contract-driven capability selection (general vocabulary, never goal-specific)
# Expanded to cover advisory goals (learning, career, finance, vague "get rich")
CONTRACT_CAP_RULES: List[Tuple[Tuple[str, ...], str]] = [
    # Business workflows
    (("financial", "revenue", "model", "budget", "forecast"), "sheets.create"),
    (("market", "competitor", "research", "viability"), "web.research"),
    (("deck", "presentation", "slides", "pitch"), "slides.create"),
    (("meeting", "kickoff", "schedule"), "calendar.create_event"),
    (("task", "follow-up", "action"), "tasks.create"),
    (("report", "summary", "plan", "analysis", "assessment", "recommendation"), "docs.create"),
    
    # Advisory goals: learning
    (("learning", "curriculum", "roadmap", "course", "study"), "docs.create"),
    (("resource", "book", "tutorial", "documentation"), "web.research"),
    (("schedule", "timeline", "milestone"), "docs.create"),
    (("project", "portfolio", "hands-on"), "docs.create"),
    
    # Advisory goals: career
    (("career", "job", "interview", "promotion", "skill"), "docs.create"),
    (("resume", "cv", "portfolio"), "docs.create"),
    (("networking", "mentor", "coach"), "web.research"),
    
    # Advisory goals: finance
    (("budget", "savings", "investment", "expense"), "sheets.create"),
    (("income", "revenue", "cashflow"), "sheets.create"),
    (("tax", "deduction", "credit"), "web.research"),
    
    # Vague goals: "get rich" / "make money"
    (("rich", "wealth", "money", "income"), "web.research"),
    (("strategy", "approach", "method"), "docs.create"),
    
    # Phase 10: Visual/travel/creative goals
    (("image", "photo", "picture", "visual", "illustration"), "imagen.generate_image"),
    (("travel", "island", "beach", "vacation", "destination", "trip"), "imagen.generate_image"),
]

class WorkflowCompiler:
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    async def compile(self, goal: str, intent: MissionIntent, constitution: MissionConstitution,
                      attachment=None, context_bundle=None, outcome_contract=None) -> List[MissionNode]:
        text = goal.lower()
        selected: List[Tuple[str, str]] = []
        for terms, cap_id in KEYWORD_RULES:
            hit = next((t for t in terms if t in text), None)
            if hit and cap_id in constitution.allowed_capabilities and cap_id not in [c for c, _ in selected]:
                selected.append((cap_id, hit))

        # Phase 8B: merge contract-driven capabilities
        for cap_id, term in self._contract_caps(outcome_contract, constitution):
            if cap_id not in [c for c, _ in selected]:
                selected.append((cap_id, term))

        conditions: List[Tuple[str, NodeCondition, str]] = []
        if "war room" in text or "escalation" in text:
            if "gmail.search" not in [c for c, _ in selected]:
                selected.append(("gmail.search", "escalation"))
            conditions.append(("calendar.create_event",
                               NodeCondition(source_capability="gmail.search", op="any_contains",
                                             field="subject", value="urgent"), "War Room"))
        if "refund" in text:
            if "gmail.search" not in [c for c, _ in selected]:
                selected.append(("gmail.search", "refund"))
            conditions.append(("docs.create",
                               NodeCondition(source_capability="gmail.search", op="any_contains",
                                             field="subject", value="refund"), "Refund Brief"))

        # multimodal needs the email that carries the attachment
        if "multimodal.analyze" in [c for c, _ in selected] and "gmail.search" not in [c for c, _ in selected]:
            selected.append(("gmail.search", "screenshot"))

        # An uploaded attachment forces multimodal analysis even without keywords
        if attachment and "multimodal.analyze" not in [c for c, _ in selected]:
            selected.append(("multimodal.analyze", "attachment"))

        # Phase 3: If context bundle contains Drive files, prefer reading them when relevant
        if context_bundle and hasattr(context_bundle, "drive_items") and context_bundle.drive_items:
            drive_terms = ("drive", "file", "contract", "concept", "launch notes", "ghost")
            entities_str = " ".join(getattr(context_bundle, "goal_entities", []) or []).lower()
            if any(t in text for t in drive_terms) or any(t in entities_str for t in drive_terms):
                if "drive.read" in constitution.allowed_capabilities and "drive.read" not in [c for c, _ in selected]:
                    selected.append(("drive.read", "context"))

        # Phase 4: If the Outcome Contract requires external research, add web.research.
        # Controlled trigger — only fires when the contract explicitly needs it.
        # Phase 4: If the Outcome Contract requires external research, add web.research
        if outcome_contract and getattr(outcome_contract, "needs_external_research", False):
            if "web.research" in constitution.allowed_capabilities and "web.research" not in [c for c, _ in selected]:
                selected.append(("web.research", "contract"))

        if not any(c in SYNTHESIS_CAPS for c, _ in selected):
            selected.append(("docs.create", "fallback"))

        # Pass 1: create every node first so each gets its real node_id (a UUID) —
        # capability_id strings must never be used as depends_on values.
        research_ids = [c for c, _ in selected if c in RESEARCH_CAPS]
        nodes: List[MissionNode] = []
        by_cap = {}
        for cap_id, term in selected:
            cap = self.network.get(cap_id)
            inputs = self._default_inputs(cap_id, intent, None)
            if cap_id == "multimodal.analyze" and attachment is not None:
                inputs["attachment"] = attachment
            if cap_id == "drive.read" and context_bundle and hasattr(context_bundle, "drive_items"):
                # Read the first discovered file from context bundle
                if context_bundle.drive_items:
                    inputs["file_id"] = context_bundle.drive_items[0].resource_id
                    inputs["title"] = context_bundle.drive_items[0].title
            if cap_id == "web.research":
                inputs["objective"] = goal
                inputs["max_results"] = 5

            # Phase 6: Assign persona based on capability (ADR-058)
            persona = persona_for_capability(cap_id)

            n = MissionNode(
                capability_id=cap_id,
                inputs=inputs,
                rationale_summary=f"Matched term '{term}' → capability {cap_id} ({cap.name}). [{persona.role}]",
                persona=persona.role,
            )
            by_cap.setdefault(cap_id, n)
            nodes.append(n)

        # Pass 2: wire synthesis-node dependencies using the real node_ids now
        # that every node exists.
        research_node_ids = [by_cap[c].node_id for c in research_ids if c in by_cap]
        for n in nodes:
            if n.capability_id in SYNTHESIS_CAPS and n.capability_id not in RESEARCH_CAPS:
                n.depends_on = [rid for rid in research_node_ids if rid != n.node_id]

        mma, g = by_cap.get("multimodal.analyze"), by_cap.get("gmail.search")
        if mma and g:
            mma.depends_on = [g.node_id]

        for cap_id, cond, title in conditions:
            cap = self.network.get(cap_id)
            src = by_cap.get(cond.source_capability)
            # Phase 6: Assign persona to conditional branch nodes too
            persona = persona_for_capability(cap_id)
            nodes.append(MissionNode(
                capability_id=cap_id,
                depends_on=[src.node_id] if src else [],
                condition=cond,
                inputs=self._default_inputs(cap_id, intent, title),
                rationale_summary=f"Conditional branch: {title} runs only if {cond.source_capability} matches '{cond.value}'. [{persona.role}]",
                persona=persona.role,
            ))
        return nodes

    def _contract_caps(self, outcome_contract, constitution) -> List[Tuple[str, str]]:
        """Extract capabilities from contract deliverables/evidence vocabulary (ADR-061).
        Minimal fallback contracts (≤1 deliverable) do not expand the plan."""
        if outcome_contract is None:
            return []
        items = list(getattr(outcome_contract, "required_deliverables", []) or [])
        items += list(getattr(outcome_contract, "required_evidence", []) or [])
        if len(items) <= 1:
            return []   # minimal fallback contract — do not expand the plan
        out: List[Tuple[str, str]] = []
        for terms, cap_id in CONTRACT_CAP_RULES:
            hit = next((it for it in items if any(t in it.lower() for t in terms)), None)
            if hit and cap_id in constitution.allowed_capabilities:
                out.append((cap_id, f"contract:{hit[:30]}"))
        return out

    @staticmethod
    def _default_inputs(cap_id: str, intent: MissionIntent, title: Optional[str]) -> dict:
        if cap_id == "gmail.search":
            return {"query": intent.objective, "max_results": 5}
        if cap_id == "drive.search":
            return {"query": intent.objective}
        if cap_id == "drive.read":
            return {"file_id": "", "title": ""}
        if cap_id == "sheets.create":
            return {"title": title or f"Tracker - {intent.objective}", "headers": ["Item", "Owner", "Status"]}
        if cap_id == "sheets.read":
            return {"sheet_id": "incident_metrics", "range": "A1:B10"}
        if cap_id == "calendar.create_event":
            return {"title": title or f"Sync - {intent.objective}", "attendees": ["team@acme.dev"]}
        if cap_id == "gmail.send":
            return {"to": ["customer@acme.dev"], "subject": f"Update: {intent.objective}", "body": "Status update..."}
        if cap_id == "tasks.create":
            return {"title": f"Follow-up - {intent.objective}", "notes": ""}
        if cap_id == "slides.create":
            return {"title": title or f"Deck - {intent.objective}", "slides": ["Summary", "Impact", "Next steps"]}
        if cap_id == "chat.notify":
            return {"space": "incidents", "text": f"Update: {intent.objective}"}
        if cap_id == "people.search":
            return {"query": intent.objective}
        if cap_id == "forms.create":
            return {"title": title or f"Form - {intent.objective}", "questions": ["Status?"]}
        if cap_id == "multimodal.analyze":
            return {"attachment": {"type": "image/png", "name": "error.png",
                                   "text": "500 Internal Server Error\nDB_TIMEOUT"}}
        if cap_id == "web.research":
            return {"objective": intent.objective, "max_results": 5}
        if cap_id == "veo.generate_video":
            return {"prompt": f"Launch video for {intent.objective}"}
        if cap_id == "lyria.generate_audio":
            return {"prompt": f"Executive audio briefing for {intent.objective}"}
        # Phase 10: Image generation default inputs
        if cap_id == "imagen.generate_image":
            return {"prompt": f"Photorealistic, vibrant photography-style image for: {intent.objective}"}
        return {"title": title or f"Report - {intent.objective}", "content": "Initial details..."}