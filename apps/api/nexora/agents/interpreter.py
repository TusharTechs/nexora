"""Stage 1 of the pipeline: restate a raw goal as a structured MissionIntent.

Runs as a Gemini turn (ADK agent → Unified LLM Client). If no backend is
configured, or the model call fails, it degrades to a deterministic pass-through
so the mission still proceeds — the Outcome Contract stage does the load-bearing
"what does success mean" reasoning.
"""
import json
import re

from nexora.core.model_router import ModelRouter, ModelTier
from packages.core.models import MissionIntent

_INSTRUCTION = (
    "You are NEXORA's Mission Interpreter. Restate the user's goal as a compact, "
    "structured intent. Output ONLY JSON:\n"
    '{"objective": "one-sentence restatement in the user\'s own framing",\n'
    ' "entities": ["concrete people, places, companies, systems, dates named"],\n'
    ' "constraints": ["explicit limits: budget, deadline, tone, do-nots"],\n'
    ' "success_criteria": ["1-4 checkable conditions that would make this done"],\n'
    ' "ambiguity_score": 0.0-1.0 (how under-specified the goal is),\n'
    ' "confidence": 0.0-1.0}\n'
    "Be faithful — do not invent scope the user did not ask for."
)


class MissionInterpreter:
    def __init__(self, router: ModelRouter, call_fn=None):
        self.router = router
        self.call_fn = call_fn  # test seam

    async def interpret(self, goal: str) -> MissionIntent:
        self.router.route(ModelTier.T1)
        raw = await self._call(goal)
        parsed = self._parse(raw)
        if parsed:
            try:
                return MissionIntent(
                    objective=str(parsed.get("objective") or goal)[:400],
                    entities=[str(e) for e in (parsed.get("entities") or [])][:12],
                    constraints=[str(c) for c in (parsed.get("constraints") or [])][:8],
                    success_criteria=[str(s) for s in (parsed.get("success_criteria") or [])][:6],
                    ambiguity_score=_clamp(parsed.get("ambiguity_score", 0.3)),
                    confidence=_clamp(parsed.get("confidence", 0.8)),
                )
            except Exception:
                pass
        # Deterministic degradation — never block the mission here.
        return MissionIntent(objective=goal, ambiguity_score=0.5, confidence=0.6)

    async def _call(self, goal: str) -> str:
        if self.call_fn:
            return self.call_fn(goal)
        try:
            from nexora.core.adk_runtime import try_run_agent
            txt = await try_run_agent(role="Mission Interpreter",
                                      instruction=_INSTRUCTION,
                                      task=f"Goal:\n{goal}")
            if txt and txt.strip():
                return txt
        except Exception:
            pass
        try:
            from nexora.core.llm_client import llm_available, llm_generate
            if llm_available():
                return await llm_generate(f"{_INSTRUCTION}\n\nGoal:\n{goal}", temperature=0.1)
        except Exception:
            pass
        return ""

    @staticmethod
    def _parse(text: str):
        if not text:
            return None
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None


def _clamp(v, lo=0.0, hi=1.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except Exception:
        return 0.5
