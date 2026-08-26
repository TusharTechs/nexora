"""Workflow Forge — successful missions become reusable templates (ADR-044)."""
import uuid
from typing import Dict, List, Optional
from packages.core.models import Mission, MissionNode, WorkflowTemplate


class WorkflowForge:
    def __init__(self, network):
        self.network = network
        self._templates: Dict[str, WorkflowTemplate] = {}

    def forge(self, mission: Mission) -> WorkflowTemplate:
        success = [n for n in mission.nodes if n.status == "SUCCESS"]
        blueprint = [{"node_id": n.node_id, "capability_id": n.capability_id,
                      "depends_on": n.depends_on, "inputs": n.inputs} for n in success]
        cost = sum(self.network.get(b["capability_id"]).estimated_cost_usd
                   for b in blueprint if self.network.get(b["capability_id"]))
        latency = sum(self.network.get(b["capability_id"]).estimated_latency_ms
                      for b in blueprint if self.network.get(b["capability_id"]))
        t = WorkflowTemplate(
            template_id=str(uuid.uuid4()),
            name=f"Forged: {mission.goal[:60]}",
            source_mission_id=mission.mission_id,
            blueprint=blueprint,
            expected_cost_usd=round(cost, 6),
            expected_runtime_ms=latency,
        )
        self._templates[t.template_id] = t
        return t

    def get(self, template_id: str) -> Optional[WorkflowTemplate]:
        return self._templates.get(template_id)

    def list(self) -> List[WorkflowTemplate]:
        return list(self._templates.values())

    def build_nodes(self, template: WorkflowTemplate) -> List[MissionNode]:
        idmap: Dict[str, str] = {}
        nodes: List[MissionNode] = []
        for step in template.blueprint:
            node = MissionNode(
                capability_id=step["capability_id"],
                inputs=dict(step.get("inputs") or {}),
                depends_on=[idmap[d] for d in step.get("depends_on", []) if d in idmap],
                rationale_summary=f"From forged workflow {template.template_id}.",
            )
            idmap[step["node_id"]] = node.node_id
            nodes.append(node)
        return nodes

    def clear(self):
        self._templates.clear()