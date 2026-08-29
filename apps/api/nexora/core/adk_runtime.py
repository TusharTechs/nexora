"""Google ADK runtime — NEXORA's specialist workforce runs as ADK agents
(ADR-068, ADR-073).

Each NEXORA persona (Research Analyst, Writer, Financial Analyst, Designer,
Coordinator, Visual Designer) is a `google.adk` `LlmAgent` whose `instruction`
is the persona's system prompt. The Architect (plan compiler), the composer, and
the QA Auditor invoke these agents through an ADK `Runner`.

When `NEXORA_AGENT_ENGINE` is set the Runner is backed by **Vertex AI Agent
Engine** — managed Sessions (`VertexAiSessionService`) and Memory Bank
(`VertexAiMemoryBankService`); otherwise an in-process `InMemoryRunner`.

Falls back cleanly: no `google-adk`, no backend, or any runtime error → callers
drop to the Unified LLM Client and then to deterministic templates. The hermetic
test suite blanks the relevant env vars, so it never touches ADK or Agent Engine.
"""
from __future__ import annotations

import os
from typing import List, Optional

_WARNED = False


def adk_available() -> bool:
    if os.getenv("NEXORA_ADK", "1") != "1":
        return False
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GCP_PROJECT_ID")):
        return False
    try:
        import google.adk  # noqa: F401
        return True
    except Exception:
        return False


def _configure_genai_env() -> None:
    """Point google-genai (used by ADK) at the same backend NEXORA uses."""
    if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    backend = os.getenv("NEXORA_LLM_BACKEND", "auto")
    project = os.getenv("GCP_PROJECT_ID", "")
    if project and (backend == "vertex" or (backend == "auto" and not os.getenv("GEMINI_API_KEY"))):
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project)
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION",
                              os.getenv("GCP_GENAI_LOCATION", "global"))


def _model() -> str:
    return os.getenv("NEXORA_MODEL_T2", "gemini-3.5-flash")


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_") or "agent"


def _agent_engine_id() -> str:
    """The numeric reasoningEngine id, if NEXORA is wired to Agent Engine."""
    v = os.getenv("NEXORA_AGENT_ENGINE", "").strip()
    return v.rsplit("/", 1)[-1] if v else ""


def _runner(agent):
    """An ADK Runner. When NEXORA_AGENT_ENGINE is set the workforce runs with
    Vertex AI Agent Engine's **managed Sessions + Memory Bank** instead of the
    in-process services; otherwise an InMemoryRunner."""
    engine_id = _agent_engine_id()
    if engine_id:
        try:
            from google.adk.memory import VertexAiMemoryBankService
            from google.adk.runners import Runner
            from google.adk.sessions import VertexAiSessionService
            proj = os.getenv("GCP_PROJECT_ID", "")
            loc = os.getenv("GCP_LOCATION", "us-central1")
            return Runner(
                agent=agent, app_name=engine_id,
                session_service=VertexAiSessionService(project=proj, location=loc,
                                                       agent_engine_id=engine_id),
                memory_service=VertexAiMemoryBankService(project=proj, location=loc,
                                                         agent_engine_id=engine_id),
            ), engine_id
        except Exception:
            pass
    from google.adk.runners import InMemoryRunner
    return InMemoryRunner(agent=agent, app_name="nexora"), "nexora"


async def run_agent(*, role: str, instruction: str, task: str,
                    tools: Optional[List] = None, model: Optional[str] = None) -> str:
    """Run one ADK LlmAgent turn and return its final text. Raises on any failure
    so callers can fall back."""
    _configure_genai_env()
    from google.adk.agents import LlmAgent
    from google.genai import types

    agent = LlmAgent(name=_slug(role), model=model or _model(),
                     instruction=instruction, tools=tools or [])
    runner, app_name = _runner(agent)
    session = await runner.session_service.create_session(
        app_name=app_name, user_id="mission")
    message = types.Content(role="user", parts=[types.Part(text=task)])
    final = ""
    async for event in runner.run_async(user_id="mission", session_id=session.id,
                                        new_message=message):
        if event.is_final_response() and event.content and event.content.parts:
            final = "".join(p.text or "" for p in event.content.parts)
    return final


async def try_run_agent(*, role: str, instruction: str, task: str) -> Optional[str]:
    """Best-effort: return the agent's text, or None if ADK can't run."""
    global _WARNED
    if not adk_available():
        return None
    try:
        return await run_agent(role=role, instruction=instruction, task=task)
    except Exception as e:  # pragma: no cover - network/runtime dependent
        if not _WARNED:
            print(f"[adk] falling back to direct LLM client: {e}")
            _WARNED = True
        return None
