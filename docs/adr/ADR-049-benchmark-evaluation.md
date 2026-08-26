# ADR-049: Benchmark Evaluation is Deterministic
Status: Accepted.

Decision: Benchmark missions are data (goal + expected artifacts/nodes/evidence).
Evaluation is deterministic: artifact types match, expected nodes succeeded, evidence
count meets threshold. Score is (artifact_match + node_match + evidence_match) / 3.
Missions pass if score == 1.0.

Consequences: Non-scripted goals can be evaluated automatically. Judges can create
new benchmarks by adding to BENCHMARKS list. No LLM grading needed.