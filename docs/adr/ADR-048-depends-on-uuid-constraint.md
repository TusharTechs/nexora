# ADR-048: depends_on Must Use Node UUIDs
Status: Accepted.

Context: MissionNode.depends_on must contain node_id UUIDs, never capability-id
strings. This bug appeared in Phase 2, was fixed, then reappeared in Phase 7 when
the compiler was rewritten.

Decision: Compiler MUST use two-pass pattern: (1) build all MissionNode objects,
(2) wire depends_on using .node_id values from a capability_id→node map. Single-pass
patterns that put capability-ids into depends_on are forbidden.

Consequences: Synthesis nodes correctly wait for research nodes. Tests verify
dependency ordering. Future compiler rewrites must preserve this pattern.