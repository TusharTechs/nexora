# ADR-057: Adaptive Replanning
Status: Accepted.

Context: Deterministic recovery (Replanner) handles individual node failures via
fallback maps. But when semantic verification reports contract-level incompleteness
(missing deliverables, insufficient evidence), a different replanning path is needed
that understands the contract gap and proposes follow-up work.

Decision: AdaptiveReplanner proposes constrained follow-up plans (max 3 new nodes,
max 2 cycles per mission) using the LLM. Safety boundaries:
- Cannot remove completed work
- Cannot duplicate already-completed capabilities
- Cannot weaken policy (every node re-passes Policy Engine)
- Must pass Plan Critic
- Respects mission constraints + approval policy

Deterministic recovery handles individual failures first. Adaptive replanning runs
only when semantic verification reports incompleteness AFTER the full plan executed.

Consequences: NEXORA can say "I am not done yet" and produce a real follow-up plan
that addresses the specific gaps identified by the semantic verifier, rather than
declaring mission complete when it isn't.