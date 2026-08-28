# ADR-060: Unified LLM Client (Vertex + Gemini)
Status: Accepted.

Context: LLM calls were scattered across five modules, each hard-wired to the
Gemini API. Vertex AI (same Gemini models, GCP billing/credits, native Veo/Lyria
home) was unreachable, and a single-backend outage would degrade planning.

Decision: All LLM call sites delegate to core/llm_client.py. NEXORA_LLM_BACKEND
selects gemini|vertex|auto; auto prefers Vertex when GCP_PROJECT_ID is set and
falls back to Gemini on failure. Vertex auth uses ADC (gcloud application-default
or service account), cached ~50 min. Model ids stay env-driven via ModelRouter.

Consequences: Backend choice is env-only. Outages self-heal via fallback.
Veo/Lyria (Phases 10-11) plug into the same Vertex credentials.