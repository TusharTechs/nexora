import os
from packages.core.models import MissionState, utcnow, ActionReceipt, Mission
from nexora.core.state_machine import MissionStateMachine
from nexora.core.policy_engine import PolicyEngine
from nexora.core.task_dispatcher import LocalTaskDispatcher, CloudTasksDispatcher
from nexora.core.security import ContentFirewall
from nexora.core.audit import AuditTrail, AuditEntry, AuditKind
from nexora.agents.node_executor import NodeExecutor, ApprovalRequiredError
from nexora.agents.supervisor import MissionSupervisor

MAX_RETRIES = 2
SATISFIED = {"SUCCESS", "SKIPPED"}


class MissionRuntime:
    def __init__(self, repo, network, registry, bus, firewall: ContentFirewall, audit: AuditTrail):
        self.repo = repo
        self.network = network
        self.registry = registry
        self.bus = bus
        self.firewall = firewall
        self.audit = audit
        self.executor = NodeExecutor(PolicyEngine(network), network, registry, firewall, audit)
        self.supervisor = MissionSupervisor(repo, bus, registry, network, audit)
        if os.getenv("NEXORA_DISPATCHER") == "cloud":
            self.dispatcher = CloudTasksDispatcher(
                os.getenv("GCP_PROJECT_ID", ""), os.getenv("GCP_REGION", "us-central1"),
                "nexora-workers", os.getenv("NEXORA_WORKER_URL", "http://localhost:8000"))
        else:
            self.dispatcher = LocalTaskDispatcher(self.process_node)

    async def dispatch(self, mission_id: str, node_id: str):
        await self.dispatcher.dispatch_node(mission_id, node_id)

    def _eval_condition(self, mission: Mission, node) -> bool:
        cond = node.condition
        src = next((n for n in mission.nodes if n.capability_id == cond.source_capability), None)
        if not src:
            return False
        data = src.outputs.get(cond.path, [])
        if cond.op == "min_count":
            return len(data) >= cond.value
        if cond.op == "any_contains":
            return any(str(cond.value).lower() in str(item.get(cond.field, "")).lower()
                       for item in data if isinstance(item, dict))
        return False

    def _cascade_skip(self, mission: Mission, failed_id: str):
        changed = True
        while changed:
            changed = False
            for n in mission.nodes:
                if n.status == "PENDING" and any(d == failed_id or
                        (self._node(mission, d) and self._node(mission, d).status == "FAILED")
                        for d in n.depends_on):
                    n.status = "SKIPPED"
                    n.completed_at = utcnow()
                    n.rationale_summary += " [skipped: dependency failed]"
                    self.audit.record(AuditEntry(
                        mission_id=mission.mission_id, node_id=n.node_id,
                        kind=AuditKind.NODE_SKIPPED, severity="WARN",
                        title="skipped:dependency_failed",
                        detail=f"{n.capability_id} skipped because {failed_id} failed."))
                    changed = True

    @staticmethod
    def _node(mission, node_id):
        return next((n for n in mission.nodes if n.node_id == node_id), None)

    async def process_node(self, mission_id: str, node_id: str):
        mission = await self.repo.get(mission_id)
        if not mission:
            return
        node = self._node(mission, node_id)
        if node is None or node.status != "PENDING":
            return

        if node.condition and not self._eval_condition(mission, node):
            node.status = "SKIPPED"
            node.completed_at = utcnow()
            node.rationale_summary += " [condition not met]"
            self.audit.record(AuditEntry(
                mission_id=mission_id, node_id=node_id, kind=AuditKind.NODE_SKIPPED,
                severity="INFO", title="skipped:condition",
                detail=f"{node.capability_id} condition was not met; branch SKIPPED."))
            await self.repo.save(mission)
            await self.bus.publish("MISSION.NODE.SKIPPED", {"mission_id": mission_id, "node_id": node_id})
            for dep in mission.nodes:
                if node_id in dep.depends_on and dep.status == "PENDING" and \
                   all(self._node(mission, d).status in SATISFIED for d in dep.depends_on):
                    await self.dispatch(mission_id, dep.node_id)
            await self.supervisor.check_completion(mission_id)
            return

        node.status = "RUNNING"
        node.started_at = utcnow()
        await self.repo.save(mission)
        await self.bus.publish("MISSION.NODE.STARTED", {"mission_id": mission_id, "node_id": node_id})

        cap = self.network.get(node.capability_id)
        if cap and not self.supervisor.can_spend(mission, cap):
            node.status = "FAILED"
            node.completed_at = utcnow()
            node.rationale_summary += " [budget exceeded — circuit breaker]"
            self.audit.record(AuditEntry(
                mission_id=mission_id, node_id=node_id, kind=AuditKind.BUDGET_BREAKER,
                severity="ALERT", title="budget_circuit_breaker",
                detail=f"{node.capability_id} not executed: budget exhausted."))
            await self.repo.save(mission)
            await self.bus.publish("MISSION.NODE.FAILED", {"mission_id": mission_id, "node_id": node_id, "error": "budget"})
            self._cascade_skip(mission, node_id)
            await self.repo.save(mission)
            await self.supervisor.check_completion(mission_id)
            return

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
        except PermissionError as e:
            node.status = "FAILED"
            node.completed_at = utcnow()
            self.audit.record(AuditEntry(
                mission_id=mission_id, node_id=node_id, kind=AuditKind.NODE_FAILED,
                severity="ALERT", title="policy_blocked",
                detail=str(e)))
            await self.bus.publish("MISSION.NODE.FAILED", {"mission_id": mission_id, "node_id": node_id, "error": str(e)})
            self._cascade_skip(mission, node_id)
        except Exception as e:
            if node.retries < MAX_RETRIES:
                node.retries += 1
                node.status = "PENDING"
                await self.repo.save(mission)
                await self.bus.publish("MISSION.NODE.RETRY", {"mission_id": mission_id, "node_id": node_id, "retry": node.retries})
                await self.dispatch(mission_id, node_id)
                return
            node.status = "FAILED"
            node.completed_at = utcnow()
            self.audit.record(AuditEntry(
                mission_id=mission_id, node_id=node_id, kind=AuditKind.NODE_FAILED,
                severity="ALERT", title="execution_failed",
                detail=str(e)[:500]))
            await self.bus.publish("MISSION.NODE.FAILED", {"mission_id": mission_id, "node_id": node_id, "error": str(e)})
            self._cascade_skip(mission, node_id)

        await self.repo.save(mission)

        if node.status in SATISFIED:
            for dep in mission.nodes:
                if node_id in dep.depends_on and dep.status == "PENDING":
                    if all(self._node(mission, d).status in SATISFIED for d in dep.depends_on):
                        await self.dispatch(mission_id, dep.node_id)

        await self.supervisor.check_completion(mission_id)