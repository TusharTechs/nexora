"""Durable state (ADR-035, ADR-071).

Missions and Mission Schedules persist to Firestore in production
(NEXORA_REPO=firestore) and to memory otherwise. Both honour
FIRESTORE_EMULATOR_HOST for a zero-cost local run.
"""
import os
from typing import Dict, List, Optional, Protocol

from packages.core.models import Mission, MissionSchedule


# ---------------------------------------------------------------- Missions

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

    def clear(self):
        self._store.clear()


def _firestore_async_client(project: str):
    from google.cloud.firestore import AsyncClient  # lazy
    return AsyncClient(project=project)


class FirestoreMissionRepository:
    """Durable state. Honors FIRESTORE_EMULATOR_HOST for zero-cost local runs.

    Degrades to an in-process store if Firestore is unreachable (API not enabled,
    no `(default)` database, missing IAM) so a misconfiguration can never brick a
    running demo — it just logs a warning and stops being durable."""
    def __init__(self, project_id: str):
        self.project_id = project_id
        self._client = None
        self._fallback: Optional[InMemoryMissionRepository] = None

    def client(self):
        if self._client is None:
            self._client = _firestore_async_client(self.project_id)
        return self._client

    def _degrade(self, err) -> InMemoryMissionRepository:
        if self._fallback is None:
            import logging
            logging.getLogger("nexora.repo").warning(
                "Firestore unavailable (%s) — falling back to in-memory state. "
                "Enable firestore.googleapis.com and create a (default) database "
                "for durable missions.", err)
            self._fallback = InMemoryMissionRepository()
        return self._fallback

    async def save(self, mission: Mission) -> None:
        if self._fallback is not None:
            return await self._fallback.save(mission)
        try:
            await self.client().collection("missions").document(mission.mission_id).set(
                mission.model_dump(mode="json"))
        except Exception as e:
            await self._degrade(e).save(mission)

    async def get(self, mission_id: str) -> Optional[Mission]:
        if self._fallback is not None:
            return await self._fallback.get(mission_id)
        try:
            snap = await self.client().collection("missions").document(mission_id).get()
            return Mission.model_validate(snap.to_dict()) if snap.exists else None
        except Exception as e:
            return await self._degrade(e).get(mission_id)


def build_repository() -> MissionRepository:
    if os.getenv("NEXORA_REPO") == "firestore":
        return FirestoreMissionRepository(os.getenv("GCP_PROJECT_ID", "nexora-dev"))
    return InMemoryMissionRepository()


# ---------------------------------------------------------------- Schedules

class ScheduleRepository(Protocol):
    async def save(self, sched: MissionSchedule) -> None: ...
    async def delete(self, schedule_id: str) -> None: ...
    async def all(self) -> List[MissionSchedule]: ...


class InMemoryScheduleRepository:
    def __init__(self):
        self._store: Dict[str, MissionSchedule] = {}

    async def save(self, sched: MissionSchedule) -> None:
        self._store[sched.schedule_id] = sched

    async def delete(self, schedule_id: str) -> None:
        self._store.pop(schedule_id, None)

    async def all(self) -> List[MissionSchedule]:
        return list(self._store.values())

    def clear(self):
        self._store.clear()


class FirestoreScheduleRepository:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self._client = None
        self._fallback: Optional[InMemoryScheduleRepository] = None

    def client(self):
        if self._client is None:
            self._client = _firestore_async_client(self.project_id)
        return self._client

    def _degrade(self, err) -> InMemoryScheduleRepository:
        if self._fallback is None:
            import logging
            logging.getLogger("nexora.repo").warning(
                "Firestore unavailable for schedules (%s) — in-memory fallback.", err)
            self._fallback = InMemoryScheduleRepository()
        return self._fallback

    async def save(self, sched: MissionSchedule) -> None:
        if self._fallback is not None:
            return await self._fallback.save(sched)
        try:
            await self.client().collection("schedules").document(sched.schedule_id).set(
                sched.model_dump(mode="json"))
        except Exception as e:
            await self._degrade(e).save(sched)

    async def delete(self, schedule_id: str) -> None:
        if self._fallback is not None:
            return await self._fallback.delete(schedule_id)
        try:
            await self.client().collection("schedules").document(schedule_id).delete()
        except Exception as e:
            await self._degrade(e).delete(schedule_id)

    async def all(self) -> List[MissionSchedule]:
        if self._fallback is not None:
            return await self._fallback.all()
        try:
            out: List[MissionSchedule] = []
            async for snap in self.client().collection("schedules").stream():
                try:
                    out.append(MissionSchedule.model_validate(snap.to_dict()))
                except Exception:
                    continue
            return out
        except Exception as e:
            return await self._degrade(e).all()


def build_schedule_repository() -> ScheduleRepository:
    if os.getenv("NEXORA_REPO") == "firestore":
        return FirestoreScheduleRepository(os.getenv("GCP_PROJECT_ID", "nexora-dev"))
    return InMemoryScheduleRepository()
