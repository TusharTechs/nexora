# ADR-051: LLM Workflow Compiler with Deterministic Fallback
Status: Accepted.

Decision: LLMWorkflowCompiler converts any natural goal into a capability plan via
Gemini (T2, REST, httpx). Its output is untrusted: capabilities are validated against
the Capability Network + Constitution, dependencies rewired to node UUIDs (ADR-048).
Without GEMINI_API_KEY (or on any failure) it returns None and the keyword compiler
(ADR-031) executes. The system never hard-depends on an external model.

Consequences: Arbitrary natural goals ("prepare everything for my business") compile
when a key is present; offline/test runs remain fully deterministic.