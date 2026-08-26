from packages.core.models import MissionState, utcnow
from nexora.core.state_machine import MissionStateMachine
from nexora.core.health import HealthCalculator
from nexora.core.evidence import EvidenceGraph
from nexora.agents.verifier import VerificationAgent

TERMINAL = {"SUCCESS", "FAILED"}

class MissionSupervisor:
    def __init__(self, repo, bus, registry):
        self.repo = repo
        self.bus = bus
        self.registry = registry
        self.health = HealthCalculator()

    async def check_completion(self, mission_id: str):
        mission = await self.repo.get(mission_id)
        if not mission or mission.state not in (MissionState.EXECUTING, MissionState.BLOCKED):
            return

        statuses = [n.status for n in mission.nodes]

        if any(s == "WAITING_APPROVAL" for s in statuses):
            if mission.state == MissionState.EXECUTING:
                mission.state = MissionStateMachine.transition(mission.state, MissionState.BLOCKED)
                await self.bus.publish("MISSION.BLOCKED", {"mission_id": mission_id, "reason": "awaiting_approval"})
        elif all(s in TERMINAL for s in statuses):
            mission.state = MissionStateMachine.transition(mission.state, MissionState.VERIFYING)
            verifier = VerificationAgent(self.registry)
            mission.verification = await verifier.verify(mission_id, mission.intent, mission.artifacts)

            eg = EvidenceGraph()
            for art in mission.artifacts:
                node = next((n for n in mission.nodes if n.node_id == art.node_id), None)
                mission.evidence.append(eg.generate_evidence(
                    mission_id, f"{art.type} artifact created and verified.", art, node.node_id if node else "-"))

            passed = mission.verification.overall_status == "PASS"
            final = MissionState.COMPLETED if passed else (
                MissionState.PARTIAL_SUCCESS if mission.artifacts else MissionState.FAILED)
            mission.state = MissionStateMachine.transition(mission.state, final)
            mission.health = self.health.calculate(mission)
            await self.bus.publish("MISSION.COMPLETED" if passed else "MISSION.FAILED",
                                   {"mission_id": mission_id, "status": final.value})
        else:
            mission.health = self.health.calculate(mission)

        await self.repo.save(mission)
