# ADR-054: Semantic Verification
Status: Accepted.

Context: "All nodes succeeded" is not equivalent to "the outcome is achieved."
A mission may produce artifacts that don't satisfy the Outcome Contract (missing
sections, insufficient evidence, incomplete analysis). NEXORA must be able to
say "I am not done yet" and trigger replanning.

Decision: SemanticVerifier runs AFTER structural verification passes. It reads
the Outcome Contract and the produced artifacts/evidence, then classifies each
required deliverable as SATISFIED / PARTIAL / MISSING. With GEMINI_API_KEY, the
LLM performs a semantic check; without it, a structural fallback uses artifact
count as a coarse proxy. The report is stored on the mission and consumed by
the replan loop.

Consequences: "Mission complete" means "contract satisfied." Incomplete outcomes
feed the replan loop (Phase 5) rather than being declared done.