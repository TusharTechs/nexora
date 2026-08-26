from typing import List, Optional, Tuple
from packages.core.models import MissionNode, MissionIntent, MissionConstitution, NodeCondition
from nexora.core.capability_network import CapabilityNetwork

KEYWORD_RULES: List[Tuple[Tuple[str, ...], str]] = [
    (("email", "gmail", "inbox"), "gmail.search"),
    (("drive", "file", "contract"), "drive.search"),
    (("sheet", "spreadsheet", "tracker", "budget"), "sheets.create"),
    (("meeting", "schedule", "sync", "calendar"), "calendar.create_event"),
    (("send",), "gmail.send"),
    (("report", "doc", "write", "brief"), "docs.create"),
]
RESEARCH_CAPS = {"gmail.search", "drive.search"}
SYNTHESIS_CAPS = {"docs.create", "calendar.create_event", "gmail.send"}

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

        # Conditional branches: research outcomes decide extra work (ADR-034)
        conditions: List[Tuple[str, NodeCondition, str]] = []
        if "war room" in text or "escalation" in text:
            if ("gmail.search", ) and "gmail.search" not in [c for c, _ in selected]:
                selected.append(("gmail.search", "escalation"))
            conditions.append(("calendar.create_event",
                               NodeCondition(source_capability="gmail.search", op="any_contains",
                                             field="subject", value="urgent"),
                               "War Room"))
        if "refund" in text:
            if "gmail.search" not in [c for c, _ in selected]:
                selected.append(("gmail.search", "refund"))
            conditions.append(("docs.create",
                               NodeCondition(source_capability="gmail.search", op="any_contains",
                                             field="subject", value="refund"),
                               "Refund Brief"))

        if not selected:
            selected.append(("docs.create", "fallback"))

        # Pass 1: create every node first so each gets its real node_id (a UUID).
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

        # Pass 2: wire dependencies using the real node_ids, not capability_ids.
        research_node_ids = [by_cap[c].node_id for c, _ in selected if c in RESEARCH_CAPS]
        for n in nodes:
            if n.capability_id in SYNTHESIS_CAPS and n.capability_id not in RESEARCH_CAPS:
                n.depends_on = [rid for rid in research_node_ids if rid != n.node_id]

        for cap_id, cond, title in conditions:
            cap = self.network.get(cap_id)
            src = by_cap.get(cond.source_capability)
            nodes.append(MissionNode(
                capability_id=cap_id,
                depends_on=[src.node_id] if src else [],
                condition=cond,
                inputs=self._default_inputs(cap_id, intent, title),
                rationale_summary=f"Conditional branch: {title} runs only if {cond.source_capability} output matches '{cond.value}'.",
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
        if cap_id == "calendar.create_event":
            return {"title": title or f"Sync - {intent.objective}", "attendees": ["team@acme.dev"]}
        if cap_id == "gmail.send":
            return {"to": ["customer@acme.dev"], "subject": f"Update: {intent.objective}", "body": "Status update..."}
        return {"title": title or f"Report - {intent.objective}", "content": "Initial details..."}
