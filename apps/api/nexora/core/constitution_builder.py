from packages.core.models import MissionConstitution, MissionIntent
from nexora.core.capability_network import CapabilityNetwork


class ConstitutionBuilder:
    """Phase 6: taught organizational policies become constitutional constraints."""

    def __init__(self, network: CapabilityNetwork, memory=None):
        self.network = network
        self.memory = memory

    def build(self, mission_id: str, intent: MissionIntent) -> MissionConstitution:
        forbidden = list(intent.constraints)
        if self.memory is not None:
            for cap in self.memory.forbiddens():
                if cap not in forbidden:
                    forbidden.append(cap)
        return MissionConstitution(
            mission_id=mission_id,
            budget_usd=2.0,
            forbidden_actions=forbidden,
            allowed_capabilities=self.network.ids(),
        )