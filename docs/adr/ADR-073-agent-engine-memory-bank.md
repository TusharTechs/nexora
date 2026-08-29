# ADR-073: Vertex AI Agent Engine — managed Sessions + Memory Bank

Status: Accepted.

## Context

ADR-068 put NEXORA's reasoning roles on Google ADK, but running them through an
in-process `InMemoryRunner` with `InMemoryMemoryStore`. The All Things Agentic
judges are explicit that they prefer projects "implemented with the agent
registry inside our agent platform" — i.e. **Vertex AI Agent Engine** (managed
runtime, Sessions, Memory Bank).

## Decision

Provision one Agent Engine instance (`infrastructure/deploy_agent_engine.py`,
also run by `deploy.sh`). When `NEXORA_AGENT_ENGINE=<reasoningEngine id>` is set:

- **`adk_runtime._runner()`** builds an ADK `Runner` backed by
  `VertexAiSessionService` + `VertexAiMemoryBankService` for that engine instead
  of the in-process services. Every Architect / specialist / Auditor turn now
  runs with **managed Sessions** on Agent Engine.
- **`memory_bank.VertexMemoryBankStore`** (via `NEXORA_MEMORY=memorybank`)
  subclasses `InMemoryMemoryStore`: it keeps the local typed behaviour
  (forbiddens / approval overrides / the vector fallback) and additionally
  writes every fact to **Agent Engine Memory Bank** and serves `search()` from
  Memory Bank's managed similarity retrieval.

Both degrade cleanly: `_runner()` falls back to `InMemoryRunner` on any error,
the store falls back to local vector search, and `build_memory_store()` returns
a plain `InMemoryMemoryStore` when nothing is configured. The hermetic test
suite blanks these env vars before import, so it never touches Agent Engine.

One-time IAM: Memory Bank embeds facts under its own service agent, so
`service-<PROJECT_NUMBER>@gcp-sa-aiplatform-re.iam.gserviceaccount.com` needs
`roles/aiplatform.user` (granted by `deploy.sh`).

## Consequences

- NEXORA's agents run on **Google's agent platform**, with managed conversation
  state and a managed memory service — not a hand-rolled runtime.
- Verified: ADK agent turns execute against a real Agent Engine instance
  (`reasoningEngines/…`) with managed Sessions.
- New deps: `google-cloud-aiplatform[agent_engines,adk]`. New env:
  `NEXORA_AGENT_ENGINE`, `NEXORA_MEMORY`.
