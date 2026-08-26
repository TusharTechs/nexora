# ADR-039: Audit Trail
Status: Accepted.

Decision: Every security-relevant event (firewall detection, policy decision, approval
request/decision, node execution, failure, budget breaker) is appended to an Audit Trail
with `mission_id`, `trace_id`, `kind`, `severity`, and structured `metadata`. Raw
chain-of-thought is never stored — only safe rationale summaries.

Consequences: `/api/v1/missions/{id}/audit` exposes the full audit history. The UI
Security Center reads this endpoint to show what NEXORA decided and why.