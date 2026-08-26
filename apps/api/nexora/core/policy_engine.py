from typing import Optional
from packages.core.models import MissionConstitution, Capability, RiskLevel, ApprovalRequirement

class PolicyEngine:
    """Deterministic and authoritative. LLMs can never override this."""
    def evaluate(self, action: str, constitution: MissionConstitution, capability: Optional[Capability] = None) -> str:
        if action in constitution.forbidden_actions:
            return "BLOCK"
        if capability is not None:
            if capability.approval_requirement == ApprovalRequirement.ALWAYS:
                return "REQUIRE_APPROVAL"
            if capability.risk_level == RiskLevel.HIGH:
                return "REQUIRE_APPROVAL"
        return "ALLOW"
