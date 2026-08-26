from packages.core.models import MissionHealth, Mission, RiskLevel
from nexora.core.capability_network import CapabilityNetwork

RISK_SCORE = {RiskLevel.LOW: 0.0, RiskLevel.MEDIUM: 0.3, RiskLevel.HIGH: 0.7}

class HealthCalculator:
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    def calculate(self, mission: Mission) -> MissionHealth:
        total = len(mission.nodes)
        done = sum(1 for n in mission.nodes if n.status in ("SUCCESS", "SKIPPED"))
        consumed = sum(r.cost_usd for r in mission.receipts)
        budget = mission.constitution.budget_usd if mission.constitution else 0.0
        risk = max([RISK_SCORE.get(self.network.get(r.capability_id).risk_level, 0.0)
                    for r in mission.receipts
                    if self.network.get(r.capability_id)], default=0.0)
        return MissionHealth(
            mission_id=mission.mission_id,
            completion_percentage=(done / total * 100) if total else 0.0,
            evidence_coverage=mission.verification.evidence_coverage if mission.verification else 0.0,
            policy_risk_score=min(1.0, risk),
            budget_consumed_usd=round(consumed, 6),
            budget_remaining_usd=round(budget - consumed, 6),
            blocked_objectives=[n.capability_id for n in mission.nodes if n.status in ("FAILED", "SKIPPED")],
            failed_nodes=[n.node_id for n in mission.nodes if n.status == "FAILED"],
            retry_count=sum(n.retries for n in mission.nodes),
            current_execution_state=mission.state,
            replan_count=0,
        )
