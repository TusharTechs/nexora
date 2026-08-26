from typing import List, Optional, Tuple
from packages.core.models import MissionNode, MissionIntent, MissionConstitution, NodeCondition
from nexora.core.capability_network import CapabilityNetwork

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
    (("audio", "briefing"), "lyria.generate_audio"),
]
RESEARCH_CAPS = {"gmail.search", "drive.search", "multimodal.analyze", "sheets.read", "people.search"}
SYNTHESIS_CAPS = {"docs.create", "calendar.create_event", "gmail.send", "slides.create",
                  "chat.notify", "tasks.create", "forms.create",
                  "veo.generate_video", "lyria.generate_audio"}

class WorkflowCompiler:
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    async def compile(self, goal: str, intent: MissionIntent, constitution: MissionConstitution) -> List[MissionNode]:
        text = goal.lower()
        selected: List[Tuple[str, str]] = []
        for terms, cap_id in KEYWORD_RULES:
            hit = next((t for t in terms if t in text), None)
            if hit and cap_id in constitution.allowed_capabilities and cap_id not in [c for c, _ in selected]:
                selected.append((cap_id, hit))

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

        if not selected:
            selected.append(("docs.create", "fallback"))

        # Pass 1: create every node first so each gets its real node_id (a UUID) —
        # capability_id strings must never be used as depends_on values.
        research_ids = [c for c, _ in selected if c in RESEARCH_CAPS]
        nodes: List[MissionNode] = []
        by_cap = {}
        for cap_id, term in selected:
            cap = self.network.get(cap_id)
            n = MissionNode(
                capability_id=cap_id,
                inputs=self._default_inputs(cap_id, intent, None),
                rationale_summary=f"Matched term '{term}' → capability {cap_id} ({cap.name}).",
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
            nodes.append(MissionNode(
                capability_id=cap_id,
                depends_on=[src.node_id] if src else [],
                condition=cond,
                inputs=self._default_inputs(cap_id, intent, title),
                rationale_summary=f"Conditional branch: {title} runs only if {cond.source_capability} matches '{cond.value}'.",
            ))
        return nodes

    @staticmethod
    def _default_inputs(cap_id: str, intent: MissionIntent, title: Optional[str]) -> dict:
        if cap_id == "gmail.search":
            return {"query": intent.objective, "max_results": 5}
        if cap_id == "drive.search":
            return {"query": intent.objective}
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
        if cap_id == "veo.generate_video":
            return {"prompt": f"Launch video for {intent.objective}"}
        if cap_id == "lyria.generate_audio":
            return {"prompt": f"Executive audio briefing for {intent.objective}"}
        return {"title": title or f"Report - {intent.objective}", "content": "Initial details..."}