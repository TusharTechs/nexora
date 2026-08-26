from typing import List
from packages.core.models import MissionNode, MissionConstitution
from nexora.core.capability_network import CapabilityNetwork

class PlanCritic:
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    async def critique(self, nodes: List[MissionNode], constitution: MissionConstitution) -> dict:
        issues = []
        for node in nodes:
            cap = self.network.get(node.capability_id)
            if not cap:
                issues.append(f"Capability {node.capability_id} not found in network")
            elif cap.capability_id not in constitution.allowed_capabilities:
                issues.append(f"Capability {cap.capability_id} not allowed by constitution")
            elif cap.estimated_cost_usd > constitution.budget_usd:
                issues.append(f"Budget violation for {cap.capability_id}")
        return {"approved": len(issues) == 0, "issues": issues, "warnings": []}
