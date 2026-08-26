"""Gemini multimodal seam (ADR-046).

In MOCK the extraction is deterministic (provider.analyze_attachment). In LIVE this is
where the T2 model would be invoked with the image bytes. The executor only consumes
the returned dict, so swapping in real Gemini never touches the runtime.
"""
from nexora.core.model_router import ModelRouter, ModelTier


class MultimodalAnalyzer:
    def __init__(self, router: ModelRouter):
        self.router = router

    def model_for(self) -> str:
        # Reserved for LIVE: route multimodal analysis to the strong tier.
        return self.router.route(ModelTier.T2)