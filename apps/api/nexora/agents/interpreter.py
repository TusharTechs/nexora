from nexora.core.model_router import ModelRouter, ModelTier
from packages.core.models import MissionIntent

class MissionInterpreter:
    """Phase 1: deterministic extraction. Phase 2+: T1 model via ModelRouter."""
    def __init__(self, router: ModelRouter):
        self.router = router

    async def interpret(self, goal: str) -> MissionIntent:
        _ = self.router.route(ModelTier.T1)  # reserved for real LLM call
        if "incident report" in goal.lower():
            return MissionIntent(
                objective="Create an incident report",
                entities=["incident"],
                success_criteria=["A Google Doc incident report exists"],
                ambiguity_score=0.1,
                confidence=0.9,
            )
        return MissionIntent(objective=goal, ambiguity_score=0.5)
