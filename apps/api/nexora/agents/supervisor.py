from packages.core.models import MissionState, utcnow
from nexora.core.state_machine import MissionStateMachine
from nexora.core.health import HealthCalculator
from nexora.core.evidence import EvidenceGraph
from nexora.core.audit import AuditTrail, AuditEntry, AuditKind
from nexora.core.policy_engine import PolicyEngine
from nexora.agents.verifier import VerificationAgent
from nexora.agents.critic import PlanCritic

TERMINAL = {"SUCCESS", "FAILED", "SKIPPED"}


class MissionSupervisor:
    def __init__(self, repo, bus, registry, network, audit: AuditTrail):
        self.repo = repo
        self.bus = bus
        self.registry = registry
        self.network = network
        self.audit = audit
        self.health = HealthCalculator(network)

    def can_spend(self, mission, capability) -> bool:
        consumed = sum(r.cost_usd for r in mission.receipts)
        budget = mission.constitution.budget_usd if mission.constitution else 0.0
        return consumed + capability.estimated_cost_usd <= budget + 1e-9

    async def check_completion(self, mission_id: str):
        mission = await self.repo.get(mission_id)
        if not mission or mission.state not in (MissionState.EXECUTING, MissionState.BLOCKED):
            return

        # Deadline check (unchanged)
        if mission.constitution and mission.constitution.deadline and utcnow() > mission.constitution.deadline:
            mission.state = MissionStateMachine.transition(mission.state, MissionState.FAILED)
            mission.health = self.health.calculate(mission)
            await self.repo.save(mission)
            await self.bus.publish("MISSION.FAILED", {"mission_id": mission_id, "reason": "deadline_exceeded"})
            return

        statuses = [n.status for n in mission.nodes]

        if any(s == "WAITING_APPROVAL" for s in statuses):
            if mission.state == MissionState.EXECUTING:
                mission.state = MissionStateMachine.transition(mission.state, MissionState.BLOCKED)
                await self.bus.publish("MISSION.BLOCKED", {"mission_id": mission_id, "reason": "awaiting_approval"})
        elif all(s in TERMINAL for s in statuses):
            mission.state = MissionStateMachine.transition(mission.state, MissionState.VERIFYING)

            # Existing structural verification (artifact existence)
            mission.verification = await VerificationAgent(self.registry).verify(
                mission_id, mission.intent, mission.artifacts)

            # Evidence graph (unchanged)
            eg = EvidenceGraph()
            for art in mission.artifacts:
                node = next((n for n in mission.nodes if n.node_id == art.node_id), None)
                mission.evidence.append(eg.generate_evidence(
                    mission_id, f"{art.type} artifact created and verified.", art, node.node_id if node else "-"))

            # Phase 2: Semantic verification (contract-aware) — ADVISORY
            if mission.outcome_contract is not None and mission.verification.overall_status == "PASS":
                from nexora.core.semantic_verifier import SemanticVerifier
                sv = SemanticVerifier()
                mission.semantic_verification = await sv.verify(
                    mission.outcome_contract, mission.artifacts,
                    mission.evidence, mission.receipts)

                # Phase 5: Adaptive replan if outcome incomplete.
                # replan_count (<2) is the loop bound; adaptive_replan_pending is
                # only a UI hint and must not itself block a second cycle.
                if (mission.semantic_verification
                        and not mission.semantic_verification.complete
                        and mission.replan_count < 2):
                    from nexora.core.adaptive_replanner import AdaptiveReplanner
                    ar = AdaptiveReplanner(self.network, PolicyEngine(self.network), PlanCritic(self.network))
                    follow_up = await ar.propose(mission, mission.semantic_verification)
                    if follow_up:
                        mission.replan_count += 1
                        mission.adaptive_replan_pending = True
                        for n in follow_up:
                            mission.nodes.append(n)
                        self.audit.record(AuditEntry(
                            mission_id=mission_id,
                            kind=AuditKind.REPLAN, severity="WARN",
                            title="adaptive_replan",
                            detail=f"Semantic verification incomplete; "
                                   f"{len(follow_up)} follow-up nodes added (cycle {mission.replan_count}).",
                        ))
                        await self.repo.save(mission)
                        # Reset terminal state to re-execute
                        mission.state = MissionStateMachine.transition(mission.state, MissionState.EXECUTING)
                        # Dispatch every follow-up node whose dependencies are
                        # already satisfied (their deps often completed in the
                        # first pass), not only the dependency-free ones.
                        done_ids = {n.node_id for n in mission.nodes
                                    if n.status in ("SUCCESS", "SKIPPED")}
                        for n in follow_up:
                            if all(d in done_ids for d in n.depends_on):
                                await self.bus.publish("MISSION.NODE.ADDED",
                                                       {"mission_id": mission_id, "node_id": n.node_id})
                                if hasattr(self, 'runtime'):
                                    await self.runtime.dispatch(mission_id, n.node_id)
                        # Re-enter execution via dispatch — use the bus to signal
                        await self.bus.publish("MISSION.REPLAN.TRIGGERED",
                                               {"mission_id": mission_id,
                                                "cycle": mission.replan_count,
                                                "new_nodes": [n.node_id for n in follow_up]})
                        return  # let the dispatch system pick up the new nodes
                    mission.adaptive_replan_pending = False
            
            # Determine final state
            structural_pass = mission.verification.overall_status == "PASS"
            semantic_pass = (mission.semantic_verification is None
                             or getattr(mission.semantic_verification, "complete", True))
            all_pass = structural_pass and semantic_pass
            
            if all_pass:
                final = MissionState.COMPLETED
            elif mission.artifacts:
                final = MissionState.PARTIAL_SUCCESS
            else:
                final = MissionState.FAILED
            
            mission.state = MissionStateMachine.transition(mission.state, final)
            mission.health = self.health.calculate(mission)
            await self.bus.publish("MISSION.COMPLETED" if all_pass else "MISSION.FAILED",
                                   {"mission_id": mission_id, "status": final.value})
        else:
            mission.health = self.health.calculate(mission)
        
        await self.repo.save(mission)