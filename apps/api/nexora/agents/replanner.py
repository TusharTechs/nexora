"""Replanner — deterministic fallback strategies (ADR-041).

When the environment invalidates a branch (API outage, rejected approval,
policy block), the Replanner proposes a degraded-but-useful alternative.
Every proposal re-passes the Plan Critic and Constitution before execution.
"""
from typing import List, Optional
from packages.core.models import MissionNode, Mission


FALLBACK_MAP = {
    "calendar.create_event": "tasks.create",   # can't meet now -> pending scheduling task
    "gmail.send": "gmail.draft",               # can't send -> safe internal draft
    "sheets.create": "docs.create",            # no sheet -> narrative doc fallback
}


class Replanner:
    def __init__(self, network):
        self.network = network

    def fallback_for(self, capability_id: str, constitution) -> Optional[str]:
        alt = FALLBACK_MAP.get(capability_id)
        if not alt:
            return None
        if alt in constitution.forbidden_actions:
            return None
        if alt not in constitution.allowed_capabilities:
            return None
        return alt

    async def build_fallback(self, mission: Mission, node: MissionNode, reason: str) -> Optional[MissionNode]:
        alt = self.fallback_for(node.capability_id, mission.constitution)
        if not alt:
            return None
        return MissionNode(
            capability_id=alt,
            depends_on=list(node.depends_on),
            inputs=self._adapt(node, alt),
            rationale_summary=(f"Replan ({reason}): {node.capability_id} invalidated; "
                               f"fallback {alt} preserves the objective in degraded form."),
        )

    async def propose(self, mission: Mission, node: MissionNode, reason: str) -> Optional[List[MissionNode]]:
        repl = await self.build_fallback(mission, node, reason)
        return [repl] if repl else None

    @staticmethod
    def _adapt(node: MissionNode, alt: str) -> dict:
        if alt == "tasks.create":
            return {"title": f"Pending scheduling: {node.inputs.get('title', 'meeting')}",
                    "notes": "Calendar unavailable; schedule manually when restored."}
        if alt == "gmail.draft":
            return {"to": node.inputs.get("to", []),
                    "subject": node.inputs.get("subject", ""),
                    "body": node.inputs.get("body", "")}
        if alt == "docs.create":
            return {"title": node.inputs.get("title", "Report"),
                    "content": "Spreadsheet unavailable; narrative fallback report."}
        return dict(node.inputs)