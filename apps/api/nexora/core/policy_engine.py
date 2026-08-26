from typing import Optional, Dict, Any
from packages.core.models import MissionConstitution, Capability, RiskLevel, ApprovalRequirement
from nexora.core.capability_network import CapabilityNetwork

DOMAIN_SENSITIVE_CAPABILITIES = {"gmail.send", "gmail.draft"}


class PolicyEngine:
    """Deterministic and authoritative. LLMs can never override this.
    Phase 6: consults organizational memory for taught approval overrides."""

    def __init__(self, network: Optional[CapabilityNetwork] = None, memory=None):
        self.network = network
        self.memory = memory

    def evaluate(self, action: str, constitution: MissionConstitution,
                 capability: Optional[Capability] = None,
                 extra_params: Optional[Dict[str, Any]] = None) -> str:
        if action in constitution.forbidden_actions:
            return "BLOCK"

        if action in DOMAIN_SENSITIVE_CAPABILITIES and extra_params:
            recipients = extra_params.get("to", []) or []
            for addr in recipients:
                if not isinstance(addr, str):
                    continue
                domain = addr.split("@")[-1].lower() if "@" in addr else addr.lower()
                for forbidden in constitution.forbidden_domains:
                    if domain == forbidden.lower() or domain.endswith("." + forbidden.lower()):
                        return "BLOCK"
                if addr.lower() in [e.lower() for e in constitution.forbidden_entities]:
                    return "BLOCK"

        if self.memory is not None and action in self.memory.approval_overrides():
            return "REQUIRE_APPROVAL"

        if capability is not None:
            if capability.approval_requirement == ApprovalRequirement.ALWAYS:
                return "REQUIRE_APPROVAL"
            if capability.risk_level == RiskLevel.HIGH:
                return "REQUIRE_APPROVAL"

        return "ALLOW"