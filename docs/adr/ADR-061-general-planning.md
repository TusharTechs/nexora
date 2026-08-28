# ADR-061: General Planning Hardening
Status: Accepted.

Context: NEXORA must handle arbitrary goals — not just business workflows, but
also advisory goals (learn AI, career growth, personal finance) and vague goals
("get rich"). Without general planning hardening, these goals produce thin plans
or fail outright.

Decision: Three mechanisms ensure every goal produces a verified outcome:
1. Contract vocabulary expansion: advisory goal terms (roadmap, learn, career,
   budget, invest) map to capabilities (docs.create, web.research, sheets.create).
2. LLM-first planning: when any LLM backend is configured, the LLM compiler is
   the primary planner, with keyword/contract path as safety net.
3. Guaranteed deliverable: every goal produces at least one artifact (researched
   plan, budget sheet, learning roadmap) or an honest insufficiency report.

Consequences: Judges can test NEXORA with any goal type and get a coherent,
verified outcome. The system never crashes or claims fake success.