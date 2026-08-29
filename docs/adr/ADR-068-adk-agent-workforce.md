# ADR-068: The workforce runs on Google ADK

Status: Accepted.

## Context

NEXORA's reasoning steps (plan compilation, per-deliverable content composition,
semantic verification) were bare calls to the Unified LLM Client. The All Things
Agentic judges explicitly prefer projects built on Google's agent platform / ADK
over hand-rolled model calls, and a genuine multi-agent structure strengthens the
Innovation criterion.

## Decision

Introduce `nexora/core/adk_runtime.py`. NEXORA's three reasoning roles are now
`google.adk` `LlmAgent`s, invoked through an ADK `Runner`:

| Role | ADK agent | Where |
| --- | --- | --- |
| **Mission Architect** | plans the capability DAG | `llm_compiler._call` |
| **Specialist workforce** | Research Analyst / Writer / Financial Analyst / Designer / Coordinator / Visual Designer — each persona is an agent whose `instruction` is its system prompt | `composer._call` |
| **QA Auditor** | verifies deliverables against the Outcome Contract | `semantic_verifier._call` |

`try_run_agent()` runs one agent turn and returns its final text; on any
failure (ADK not installed, no backend, runtime error) callers fall back to the
Unified LLM Client and then to deterministic templates. `adk_available()` gates
on `NEXORA_ADK` (default `1`) plus a configured backend, so the 136 hermetic
tests never touch ADK.

ADK's google-genai layer is pointed at the same backend NEXORA uses
(`GOOGLE_API_KEY` from `GEMINI_API_KEY`, or `GOOGLE_GENAI_USE_VERTEXAI` +
project/location for Vertex).

## Consequences

- Every deliverable is produced by a **named agent on ADK**, and planning /
  verification are separate agents — a real Architect → Workforce → Auditor
  multi-agent pipeline, not one prompt.
- The deterministic DAG, recovery, receipts and audit trail are unchanged — ADK
  sits inside each node, it does not replace the orchestrator.
- Adds `google-adk` to `requirements.txt`.
