import os
from enum import Enum

class ModelTier(str, Enum):
    T0 = "T0"   # lightweight / classification
    T1 = "T1"   # fast / general execution
    T2 = "T2"   # strong reasoning / multimodal

class ModelRouter:
    """Model IDs come ONLY from environment. No hardcoded versions."""
    def __init__(self):
        self._models = {t: os.getenv(f"NEXORA_MODEL_{t.value}", "") for t in ModelTier}

    def route(self, tier: ModelTier) -> str:
        return self._models[tier]
