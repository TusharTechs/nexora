from packages.core.models import MissionConstitution, MissionIntent
from nexora.core.capability_network import CapabilityNetwork

class ConstitutionBuilder:
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    def build(self, mission_id: str, intent: MissionIntent) -> MissionConstitution:
        return MissionConstitution(
            mission_id=mission_id,
            budget_usd=1.0,
            forbidden_actions=intent.constraints,
            allowed_capabilities=self.network.ids(),
        )
