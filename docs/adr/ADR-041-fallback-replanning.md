# ADR-041: Deterministic Fallback Replanning
Status: Accepted.

Decision: The Replanner maps invalidated capabilities to degraded alternatives
(calendar.create_event→tasks.create, gmail.send→gmail.draft, sheets.create→docs.create).
Proposals re-pass the Plan Critic and Constitution before dispatch. Retries handle
transient faults; replanning handles structural invalidation. replan_count is tracked
on the mission and surfaced in Health.

Consequences: Missions survive provider outages and rejected approvals without restart;
completed work is never discarded.