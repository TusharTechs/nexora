import os
from packages.core.models import MissionState, utcnow
from nexora.core.state_machine import MissionStateMachine
from nexora.core.policy_engine import PolicyEngine
from nexora.core.task_dispatcher import LocalTaskDispatcher, CloudTasksDispatcher
from nexora.core.event_bus import LocalEventBus
from nexora.agents.node_executor import NodeExecutor, ApprovalRequiredError
from nexora.agents.supervisor import MissionSupervisor
from packages.core.models import ActionReceipt

class MissionRuntime:
    """Owns node execution, dependency dispatch, and supervisor notification."""
    def __init__(self, repo, network, registry, bus):
        self.repo = repo
        self.network = network
        self.registry = registry
        self.bus = bus
        self.executor = NodeExecutor(PolicyEngine(), network, registry)
        self.supervisor = MissionSupervisor(repo, bus, registry)
        if os.getenv("NEXORA_DISPATCHER") == "cloud":
            self.dispatcher = CloudTasksDispatcher(
                os.getenv("GCP_PROJECT_ID", ""), os.getenv("GCP_REGION", "us-central1"),
                "nexora-workers", os.getenv("NEXORA_WORKER_URL", "http://localhost:8000"))
        else:
            self.dispatcher = LocalTaskDispatcher(self.process_node)

    async def dispatch(self, mission_id: str, node_id: str):
        await self.dispatcher.dispatch_node(mission_id, node_id)

    async def process_node(self, mission_id: str, node_id: str):
        mission = await self.repo.get(mission_id)
        if not mission:
            return
        node = next((n for n in mission.nodes if n.node_id == node_id), None)
        if node is None or node.status != "PENDING":   # idempotency vs duplicate events
            return

        node.status = "RUNNING"
        node.started_at = utcnow()
        await self.repo.save(mission)
        await self.bus.publish("MISSION.NODE.STARTED", {"mission_id": mission_id, "node_id": node_id})

        try:
            artifact, receipt = await self.executor.execute(mission_id, node, mission.constitution, mission.execution_mode)
            node.status = "SUCCESS"
            node.completed_at = utcnow()
            if artifact:
                artifact.mission_id = mission_id
                artifact.node_id = node_id
                mission.artifacts.append(artifact)
            mission.receipts.append(receipt)
            await self.bus.publish("MISSION.NODE.COMPLETED", {"mission_id": mission_id, "node_id": node_id, "capability": node.capability_id})
        except ApprovalRequiredError:
            node.status = "WAITING_APPROVAL"
            mission.receipts.append(ActionReceipt(
                mission_id=mission_id, node_id=node_id, action=node.capability_id,
                reason=node.rationale_summary, agent_id="worker", capability_id=node.capability_id,
                policy_decision="REQUIRE_APPROVAL", model_tier="T1", cost_usd=0.0,
                execution_mode=mission.execution_mode))
            await self.bus.publish("MISSION.APPROVAL_REQUESTED", {"mission_id": mission_id, "node_id": node_id})
        except Exception as e:
            node.status = "FAILED"
            node.completed_at = utcnow()
            await self.bus.publish("MISSION.NODE.FAILED", {"mission_id": mission_id, "node_id": node_id, "error": str(e)})

        await self.repo.save(mission)

        if node.status == "SUCCESS":
            for dep in mission.nodes:
                if node_id in dep.depends_on and dep.status == "PENDING":
                    if all(self._status(mission, d) == "SUCCESS" for d in dep.depends_on):
                        await self.dispatch(mission_id, dep.node_id)

        await self.supervisor.check_completion(mission_id)

    @staticmethod
    def _status(mission, node_id: str) -> str:
        n = next((x for x in mission.nodes if x.node_id == node_id), None)
        return n.status if n else "FAILED"
