from packages.core.models import MissionConstitution, MissionIntent, MemoryType
from nexora.core.capability_network import CapabilityNetwork


class ConstitutionBuilder:
    """Phase 6: taught organizational policies become constitutional constraints.
    ADR-072: also folds in the memories most relevant to this mission."""

    def __init__(self, network: CapabilityNetwork, memory=None):
        self.network = network
        self.memory = memory

    async def build(self, mission_id: str, intent: MissionIntent) -> MissionConstitution:
        forbidden = list(intent.constraints)
        relevant: list[str] = []
        if self.memory is not None:
            for cap in self.memory.forbiddens():
                if cap not in forbidden:
                    forbidden.append(cap)
            if hasattr(self.memory, "search"):
                try:
                    hits = await self.memory.search(
                        intent.objective, k=5,
                        types=[MemoryType.PREFERENCE, MemoryType.POLICY,
                               MemoryType.FACT, MemoryType.CORRECTION])
                    relevant = [h.content for h in hits]
                except Exception:
                    relevant = []
        return MissionConstitution(
            mission_id=mission_id,
            budget_usd=2.0,
            forbidden_actions=forbidden,
            allowed_capabilities=self.network.ids(),
            relevant_memories=relevant,
        )
