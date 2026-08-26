# ADR-042: Intervention Scope & Completed-Work Immutability
Status: Accepted.

Decision: Natural-language interventions parse via a sealed deterministic verb set
(stop external / remove entity / add capability). Only PENDING or WAITING_APPROVAL
nodes may be invalidated; SUCCESS nodes are immutable. Unknown instructions are safe
no-ops. LLM-based interpretation is a later seam behind the same InterventionPlan.

Consequences: Users can steer running missions ("Stop all external communication")
without risking completed artifacts or unbounded replanning.