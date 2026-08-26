from typing import Dict, Optional, Protocol
from packages.core.models import Mission

class MissionRepository(Protocol):
    async def save(self, mission: Mission) -> None: ...
    async def get(self, mission_id: str) -> Optional[Mission]: ...

class InMemoryMissionRepository:
    """Phase 1 storage. Swap for Firestore adapter in Phase 3."""
    def __init__(self):
        self._store: Dict[str, Mission] = {}

    async def save(self, mission: Mission) -> None:
        self._store[mission.mission_id] = mission

    async def get(self, mission_id: str) -> Optional[Mission]:
        return self._store.get(mission_id)
