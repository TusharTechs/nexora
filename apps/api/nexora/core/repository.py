import os
from typing import Dict, Optional, Protocol
from packages.core.models import Mission

class MissionRepository(Protocol):
    async def save(self, mission: Mission) -> None: ...
    async def get(self, mission_id: str) -> Optional[Mission]: ...

class InMemoryMissionRepository:
    def __init__(self):
        self._store: Dict[str, Mission] = {}

    async def save(self, mission: Mission) -> None:
        self._store[mission.mission_id] = mission

    async def get(self, mission_id: str) -> Optional[Mission]:
        return self._store.get(mission_id)

class FirestoreMissionRepository:
    """Durable state. Honors FIRESTORE_EMULATOR_HOST for zero-cost local runs (ADR-035)."""
    def __init__(self, project_id: str):
        self.project_id = project_id
        self._client = None

    def client(self):
        if self._client is None:
            from google.cloud.firestore import AsyncClient  # lazy
            self._client = AsyncClient(project=self.project_id)
        return self._client

    async def save(self, mission: Mission) -> None:
        await self.client().collection("missions").document(mission.mission_id).set(
            mission.model_dump(mode="json"))

    async def get(self, mission_id: str) -> Optional[Mission]:
        snap = await self.client().collection("missions").document(mission_id).get()
        if not snap.exists:
            return None
        return Mission.model_validate(snap.to_dict())

def build_repository() -> MissionRepository:
    if os.getenv("NEXORA_REPO") == "firestore":
        return FirestoreMissionRepository(os.getenv("GCP_PROJECT_ID", "nexora-dev"))
    return InMemoryMissionRepository()
