from typing import Optional, Dict, Any
from packages.core.models import MissionConstitution, Capability, RiskLevel, ApprovalRequirement
from nexora.core.capability_network import CapabilityNetwork

# Capabilities whose inputs include external recipients / addresses.
# Policy Engine inspects these for forbidden destinations.
DOMAIN_SENSITIVE_CAPABILITIES = {"gmail.send", "gmail.draft"}


class PolicyEngine:
    """Deterministic and authoritative. LLMs can never override this."""

    def __init__(self, network: Optional[CapabilityNetwork] = None):
        self.network = network

    def evaluate(
        self,
        action: str,
        constitution: MissionConstitution,
        capability: Optional[Capability] = None,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        if action in constitution.forbidden_actions:
            return "BLOCK"

        # Forbidden domain / entity enforcement (ADR-038)
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

        if capability is not None:
            if capability.approval_requirement == ApprovalRequirement.ALWAYS:
                return "REQUIRE_APPROVAL"
            if capability.risk_level == RiskLevel.HIGH:
                return "REQUIRE_APPROVAL"

        return "ALLOW"