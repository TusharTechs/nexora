# ADR-058: Persona Prompt Layer
Status: Accepted.

Context: Without specialist prompts, nodes produce generic content. A "docs.create"
node writes the same boilerplate for an incident report as for a market analysis.
Specialist personas improve artifact quality by providing role-specific instructions.

Decision: Six personas (Research Analyst, Financial Analyst, Strategist, Writer,
Coordinator, Designer) are defined as prompt templates, not agent classes. Each
capability maps deterministically to a persona via a fixed lookup table. The
persona is assigned at compile time and stored on the node; the executor/provider
injects it into LLM prompts. The system is purely additive — if persona lookup
fails, the default prompt is used.

Consequences: Artifact quality improves without architectural complexity. The
same execution pipeline is used; only the prompt changes. Personas can be
inspected in the DAG UI (each node shows its assigned role).