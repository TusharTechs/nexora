# ADR-075: Two Cloud Run deployment profiles (demo, scale)

Status: Accepted.

## Context

NEXORA's mission engine dispatches every capability node as an independent unit
of work and re-reads/writes the whole `Mission` after each one. Two runtime
choices interact badly on Cloud Run:

- **Dispatcher.** `local` runs the node graph as `asyncio` tasks inside the
  request's instance; `cloud` (Cloud Tasks) fans each node out as its own
  authenticated HTTP call, which can land on *any* instance.
- **Repository.** `memory` keeps missions in one process's RAM; `firestore`
  persists them.

`cloud` + `firestore` is the horizontally-scalable combination, but concurrent
node executions each do read-modify-write on the full mission document with no
transaction, so sibling nodes finishing close together can clobber each other's
status (observed in testing: a completed node reverting to `PENDING`, the
mission never reaching a terminal state). `local` + `memory` has no such race —
`InMemoryMissionRepository.get()` returns the *same* object every time, so all
mutations accumulate — but only if there is exactly one instance.

## Decision

`infrastructure/deploy.sh` ships two profiles, selected by `NEXORA_PROFILE`:

| | **demo** (default) | **scale** |
|---|---|---|
| Dispatcher | `local` (in-process task graph) | `cloud` (Cloud Tasks) |
| Repository | `memory` | `firestore` |
| Instances | `--min-instances=1 --max-instances=1 --no-cpu-throttling` | `--min-instances=0 --max-instances=10` |
| Scheduler | in-process 30 s loop | Cloud Scheduler → `/internal/run_due` |
| Extra IAM | — | Cloud Tasks `actAs` self-binding on the API SA |

**demo** is the default because a judge/reviewer wants a service that always
answers and always drives a mission to a verified terminal state. Its cost is
one always-on instance (~$45–55/month for 1 vCPU + 1 GiB) and the loss of
in-flight missions if that instance is ever replaced (Cloud Run recycles roughly
daily) — acceptable for a review window, where each reviewer runs their own
fresh missions.

**scale** is opt-in and carries a known limitation: the Firestore
read-modify-write race above. Fixing it (per-mission lock in the `local` path;
per-node documents or a transaction for the `cloud` path) is tracked as future
work and is not required for the demo.

`GEMINI_API_KEY` is optional in both profiles. The whole reasoning stack —
Gemini 3.5, the ADK workforce, Agent Engine Sessions + Memory Bank — runs on
Vertex AI through the service account's ADC. A key is only consumed by the
optional Gemma firewall second-opinion (ADR-074), served from the Gemini API.
Passing a key while `NEXORA_LLM_BACKEND=vertex` previously broke the ADK path:
`_configure_genai_env` copied it into `GOOGLE_API_KEY`, and `google-genai` +
`GOOGLE_GENAI_USE_VERTEXAI` then routed to the *key's* project in Vertex express
mode. `_configure_genai_env` now keeps every API key out of `google-genai`'s
view whenever Vertex is the chosen backend.

## Consequences

- `deploy.sh` is idempotent and resilient: APIs are enabled one at a time with
  retries, IAM bindings retry through transient `DEADLINE_EXCEEDED`, the Compute
  default SA is granted the Cloud Build roles new projects no longer inherit, and
  the Agent Engine step is non-fatal.
- The health check answers on `/`, `/healthz`, and `/api/v1/health` — Cloud Run's
  front end reserves the bare `/healthz` path and 404s it before the container.
- `/api/v1/config` reports the live model IDs and which Google services are
  actually wired, so the running stack is verifiable without taking anything on
  faith.
