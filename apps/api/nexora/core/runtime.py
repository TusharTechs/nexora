import os
from packages.core.models import MissionState, utcnow, ActionReceipt, Mission, MissionNode
from nexora.core.state_machine import MissionStateMachine
from nexora.core.policy_engine import PolicyEngine
from nexora.core.task_dispatcher import LocalTaskDispatcher, CloudTasksDispatcher
from nexora.core.security import ContentFirewall
from nexora.core.audit import AuditTrail, AuditEntry, AuditKind
from nexora.agents.node_executor import NodeExecutor, ApprovalRequiredError
from nexora.agents.supervisor import MissionSupervisor
from nexora.agents.replanner import Replanner
from nexora.agents.critic import PlanCritic
from nexora.core.intervention import InterventionHandler

MAX_RETRIES = 2
SATISFIED = {"SUCCESS", "SKIPPED"}
RESEARCH_CAPS = ("gmail.search", "drive.search")


class MissionRuntime:
    def __init__(self, repo, network, registry, bus, firewall: ContentFirewall, audit: AuditTrail, memory=None):
        self.repo = repo
        self.network = network
        self.registry = registry
        self.bus = bus
        self.firewall = firewall
        self.audit = audit
        self.memory = memory
        self.executor = NodeExecutor(PolicyEngine(network, memory), network, registry, firewall, audit)
        self.supervisor = MissionSupervisor(repo, bus, registry, network, audit)
        # Phase 5: Give supervisor a reference back to runtime for dispatching replan nodes
        self.supervisor.runtime = self
        self.replanner = Replanner(network)
        self.critic = PlanCritic(network)
        if os.getenv("NEXORA_DISPATCHER") == "cloud":
            self.dispatcher = CloudTasksDispatcher(
                os.getenv("GCP_PROJECT_ID", ""), os.getenv("GCP_REGION", "us-central1"),
                "nexora-workers", os.getenv("NEXORA_WORKER_URL", "http://localhost:8000"))
        else:
            self.dispatcher = LocalTaskDispatcher(self.process_node)

    async def dispatch(self, mission_id: str, node_id: str):
        await self.dispatcher.dispatch_node(mission_id, node_id)

    @staticmethod
    def _node(mission, node_id):
        return next((n for n in mission.nodes if n.node_id == node_id), None)

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

    # ---------------- Adaptive recovery (Phase 5) ----------------
    async def handle_failure(self, mission_id: str, node_id: str, reason: str):
        mission = await self.repo.get(mission_id)
        if not mission:
            return
        node = self._node(mission, node_id)
        if node is None:
            return
        if node.status != "FAILED":
            node.status = "FAILED"
            node.completed_at = node.completed_at or utcnow()
        if mission.state in (MissionState.EXECUTING, MissionState.BLOCKED):
            mission.state = MissionStateMachine.transition(mission.state, MissionState.REPLANNING)
        await self.bus.publish("MISSION.ENVIRONMENT_CHANGE_DETECTED",
                               {"mission_id": mission_id, "node_id": node_id, "change_type": reason})
        self.audit.record(AuditEntry(mission_id=mission_id, node_id=node_id,
                                     kind=AuditKind.ENVIRONMENT_CHANGE, severity="ALERT",
                                     title="environment_change",
                                     detail=f"{node.capability_id} invalidated: {reason}"))

        proposed = await self.replanner.propose(mission, node, reason)
        approved = False
        if proposed:
            critique = await self.critic.critique(proposed, mission.constitution)
            approved = critique["approved"]

        if proposed and approved:
            repl = proposed[0]
            node.replaced_by = repl.node_id
            for n in mission.nodes:
                if node_id in n.depends_on:
                    n.depends_on = [repl.node_id if d == node_id else d for d in n.depends_on]
            mission.nodes.append(repl)
            mission.replan_count += 1
            self.audit.record(AuditEntry(mission_id=mission_id, node_id=repl.node_id,
                                         kind=AuditKind.REPLAN, severity="WARN",
                                         title="replan_applied",
                                         detail=f"{node.capability_id} -> {repl.capability_id} ({reason})"))
            mission.state = MissionStateMachine.transition(mission.state, MissionState.EXECUTING)
            await self.repo.save(mission)
            await self.dispatch(mission_id, repl.node_id)
        else:
            self._cascade_skip(mission, node_id)
            mission.replan_count += 1
            self.audit.record(AuditEntry(mission_id=mission_id, node_id=node_id,
                                         kind=AuditKind.REPLAN, severity="WARN",
                                         title="replan_unavailable",
                                         detail=f"No fallback for {node.capability_id}; branch skipped."))
            mission.state = MissionStateMachine.transition(mission.state, MissionState.EXECUTING)
            await self.repo.save(mission)

        await self.supervisor.check_completion(mission_id)

    # ---------------- NL intervention (Phase 5, ADR-042) ----------------
    async def apply_intervention(self, mission: Mission, instruction: str) -> dict:
        if mission.state in (MissionState.COMPLETED, MissionState.FAILED, MissionState.PARTIAL_SUCCESS):
            raise ValueError("mission is terminal; interventions apply to running missions")
        plan = InterventionHandler().parse(instruction)
        applied, invalidated, added = [], [], []

        for action in plan.forbid_actions:
            if action not in mission.constitution.forbidden_actions:
                mission.constitution.forbidden_actions.append(action)
                applied.append(f"forbid:{action}")
        for ent in plan.remove_entities:
            if ent not in mission.constitution.forbidden_entities:
                mission.constitution.forbidden_entities.append(ent)
                applied.append(f"remove:{ent}")
            for n in mission.nodes:
                if n.status in ("PENDING", "RUNNING", "WAITING_APPROVAL"):
                    for key in ("attendees", "to"):
                        if ent in n.inputs.get(key, []):
                            n.inputs[key] = [x for x in n.inputs[key] if x != ent]

        # Invalidate only non-terminal nodes; completed work is immutable
        for n in list(mission.nodes):
            if n.capability_id in plan.fallbacks and n.status in ("PENDING", "WAITING_APPROVAL"):
                n.status = "SKIPPED"
                n.completed_at = utcnow()
                n.rationale_summary += " [invalidated: intervention]"
                invalidated.append(n.node_id)
                if self.memory is not None:
                    from packages.core.models import MemoryEntry, MemoryType, MemoryScope
                    await self.memory.add(MemoryEntry(
                        type=MemoryType.CORRECTION, scope=MemoryScope.ORG,
                        content=f"Intervention invalidated {n.capability_id}",
                        capability=n.capability_id, effect="correction",
                        provenance="intervention"))
                repl = await self.replanner.build_fallback(mission, n, "intervention")
                if repl:
                    n.replaced_by = repl.node_id
                    mission.nodes.append(repl)
                    added.append(repl.node_id)

        for cap_id in plan.add_capabilities:
            research_deps = [n.node_id for n in mission.nodes
                             if n.capability_id in RESEARCH_CAPS and n.status == "SUCCESS"]
            new = MissionNode(
                capability_id=cap_id,
                depends_on=research_deps,
                inputs=self._default_inputs(cap_id, mission),
                rationale_summary=f"Added by intervention: '{instruction}'",
            )
            mission.nodes.append(new)
            added.append(new.node_id)

        if plan.is_empty:
            return {"applied": [], "invalidated": [], "added": []}

        if invalidated or added:
            mission.replan_count += 1
        self.audit.record(AuditEntry(mission_id=mission.mission_id,
                                     kind=AuditKind.INTERVENTION, severity="WARN",
                                     title="intervention",
                                     detail=instruction[:200],
                                     metadata={"applied": applied, "invalidated": len(invalidated),
                                               "added": len(added)}))
        await self.bus.publish("MISSION.INTERVENTION",
                               {"mission_id": mission.mission_id, "instruction": instruction[:200]})

        waiting_left = any(n.status == "WAITING_APPROVAL" for n in mission.nodes)
        if mission.state == MissionState.BLOCKED and not waiting_left:
            mission.state = MissionStateMachine.transition(mission.state, MissionState.REPLANNING)
            mission.state = MissionStateMachine.transition(mission.state, MissionState.EXECUTING)

        await self.repo.save(mission)
        for nid in added:
            node = self._node(mission, nid)
            if node and node.status == "PENDING" and \
               all(self._node(mission, d).status in SATISFIED for d in node.depends_on):
                await self.dispatch(mission.mission_id, nid)
        await self.supervisor.check_completion(mission.mission_id)
        return {"applied": applied, "invalidated": invalidated, "added": added}

    @staticmethod
    def _default_inputs(cap_id: str, mission: Mission) -> dict:
        objective = mission.intent.objective if mission.intent else mission.goal
        if cap_id == "sheets.create":
            return {"title": f"Tracker - {objective}", "headers": ["Item", "Owner", "Status"]}
        if cap_id == "tasks.create":
            return {"title": f"Follow-up - {objective}", "notes": "Added by intervention."}
        return {"title": f"Report - {objective}", "content": ""}

    # ---------------- Node execution ----------------
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
            self.audit.record(AuditEntry(mission_id=mission_id, node_id=node_id,
                                         kind=AuditKind.NODE_SKIPPED, severity="INFO",
                                         title="skipped:condition",
                                         detail=f"{node.capability_id} condition not met; branch SKIPPED."))
            await self.repo.save(mission)
            await self.bus.publish("MISSION.NODE.SKIPPED", {"mission_id": mission_id, "node_id": node_id})
            for dep in mission.nodes:
                if node_id in dep.depends_on and dep.status == "PENDING" and \
                   all(self._node(mission, d).status in SATISFIED for d in dep.depends_on):
                    await self.dispatch(mission_id, dep.node_id)
            await self.supervisor.check_completion(mission_id)
            return

        provider = self.registry.provider
        if hasattr(provider, "bind"):
            provider.bind(mission_id, mission.workspace_folder_id)

        node.status = "RUNNING"
        node.started_at = utcnow()
        await self.repo.save(mission)
        await self.bus.publish("MISSION.NODE.STARTED", {"mission_id": mission_id, "node_id": node_id})

        cap = self.network.get(node.capability_id)
        if cap and not self.supervisor.can_spend(mission, cap):
            node.status = "FAILED"
            node.completed_at = utcnow()
            node.rationale_summary += " [budget exceeded — circuit breaker]"
            self.audit.record(AuditEntry(mission_id=mission_id, node_id=node_id,
                                         kind=AuditKind.BUDGET_BREAKER, severity="ALERT",
                                         title="budget_circuit_breaker",
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
            await self.repo.save(mission)
        except ApprovalRequiredError:
            node.status = "WAITING_APPROVAL"
            mission.receipts.append(ActionReceipt(
                mission_id=mission_id, node_id=node_id, action=node.capability_id,
                reason=node.rationale_summary, agent_id="worker", capability_id=node.capability_id,
                policy_decision="REQUIRE_APPROVAL", model_tier="T1", cost_usd=0.0,
                execution_mode=mission.execution_mode))
            await self.repo.save(mission)
            await self.bus.publish("MISSION.APPROVAL_REQUESTED", {"mission_id": mission_id, "node_id": node_id})
        except PermissionError as e:
            node.status = "FAILED"
            node.completed_at = utcnow()
            self.audit.record(AuditEntry(mission_id=mission_id, node_id=node_id,
                                         kind=AuditKind.NODE_FAILED, severity="ALERT",
                                         title="policy_blocked", detail=str(e)))
            await self.repo.save(mission)
            await self.bus.publish("MISSION.NODE.FAILED", {"mission_id": mission_id, "node_id": node_id, "error": str(e)})
            await self.handle_failure(mission_id, node_id, "policy_blocked")
            return
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
            self.audit.record(AuditEntry(mission_id=mission_id, node_id=node_id,
                                         kind=AuditKind.NODE_FAILED, severity="ALERT",
                                         title="execution_failed", detail=str(e)[:500]))
            await self.repo.save(mission)
            await self.bus.publish("MISSION.NODE.FAILED", {"mission_id": mission_id, "node_id": node_id, "error": str(e)})
            await self.handle_failure(mission_id, node_id, "provider_failure")
            return

        if node.status in SATISFIED:
            for dep in mission.nodes:
                if node_id in dep.depends_on and dep.status == "PENDING":
                    if all(self._node(mission, d).status in SATISFIED for d in dep.depends_on):
                        await self.dispatch(mission_id, dep.node_id)

        await self.supervisor.check_completion(mission_id)