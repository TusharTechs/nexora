from typing import List, Tuple
from packages.core.models import MissionNode, MissionIntent, MissionConstitution
from nexora.core.capability_network import CapabilityNetwork

# ADR-031: deterministic capability discovery seam. Replaced by LLM compiler later.
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
    """Reasons over the Capability Network — never over raw Google APIs."""
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    async def compile(self, goal: str, intent: MissionIntent, constitution: MissionConstitution) -> List[MissionNode]:
        text = goal.lower()
        selected: List[Tuple[str, str]] = []   # (capability_id, matched_term)
        for terms, cap_id in KEYWORD_RULES:
            hit = next((t for t in terms if t in text), None)
            if hit and cap_id in constitution.allowed_capabilities:
                if cap_id not in [c for c, _ in selected]:
                    selected.append((cap_id, hit))

        if not selected:   # safe fallback: knowledge artifact
            selected.append(("docs.create", "fallback"))

        # Pass 1: create every node first so each gets its real node_id (a UUID).
        nodes: List[MissionNode] = []
        node_id_by_cap: dict = {}
        for cap_id, term in selected:
            cap = self.network.get(cap_id)
            node = MissionNode(
                capability_id=cap_id,
                inputs=self._default_inputs(cap_id, intent),
                rationale_summary=f"Matched term '{term}' → capability {cap_id} ({cap.name}).",
            )
            nodes.append(node)
            node_id_by_cap[cap_id] = node.node_id

        # Pass 2: wire dependencies using the real node_ids, not capability_ids.
        research_node_ids = [node_id_by_cap[c] for c, _ in selected if c in RESEARCH_CAPS]
        for node in nodes:
            if node.capability_id in SYNTHESIS_CAPS and node.capability_id not in RESEARCH_CAPS:
                node.depends_on = [rid for rid in research_node_ids if rid != node.node_id]

        return nodes

    @staticmethod
    def _default_inputs(cap_id: str, intent: MissionIntent) -> dict:
        if cap_id == "gmail.search":
            return {"query": intent.objective, "max_results": 5}
        if cap_id == "drive.search":
            return {"query": intent.objective}
        if cap_id == "sheets.create":
            return {"title": f"Tracker - {intent.objective}", "headers": ["Item", "Owner", "Status"]}
        if cap_id == "calendar.create_event":
            return {"title": f"Sync - {intent.objective}", "attendees": ["team@acme.dev"]}
        if cap_id == "gmail.send":
            return {"to": ["customer@acme.dev"], "subject": f"Update: {intent.objective}", "body": "Status update..."}
        return {"title": f"Report - {intent.objective}", "content": "Initial details..."}
