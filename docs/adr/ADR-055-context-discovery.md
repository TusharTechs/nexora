# ADR-055: Context Discovery
Status: Accepted.

Context: Without pre-planning discovery, NEXORA starts every mission from zero,
ignoring the user's existing Drive files, Gmail threads, and Calendar events.
The planner then generates generic work instead of building on what already exists.

Decision: ContextDiscoveryService runs before planning. It extracts key entities
from the goal, searches Drive/Gmail/Calendar in parallel, and produces a compact
ContextBundle. The bundle is passed to the compiler so the plan builds on existing
context. Discovery failures degrade gracefully to an empty bundle.

Consequences: Missions build on existing work rather than starting from scratch.
The "Ghost Run" demo finds the existing concept doc and launch notes, then builds
a plan that complements them rather than duplicating work.