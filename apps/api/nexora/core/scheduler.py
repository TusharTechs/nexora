"""Mission Scheduler — standing instructions that run over days and weeks (ADR-069).

A `MissionSchedule` is a goal plus a cadence. `due()` returns the schedules whose
`next_run` has passed; `advance()` rolls `next_run` forward. The API exposes CRUD
plus `/internal/run_due`, which Cloud Scheduler pings every minute in production;
locally a background asyncio loop does the same. This is how a NEXORA task can
"span weeks" — the mission for next Monday simply does not exist until Monday.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from packages.core.models import MissionSchedule

_log = logging.getLogger("nexora.scheduler")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _advance(dt: datetime, cadence: str) -> datetime:
    if cadence == "daily":
        return dt + timedelta(days=1)
    if cadence == "weekly":
        return dt + timedelta(days=7)
    if cadence == "monthly":
        # simple, predictable: 28 days
        return dt + timedelta(days=28)
    if cadence == "weekdays":
        nxt = dt + timedelta(days=1)
        while nxt.weekday() >= 5:  # Sat=5, Sun=6
            nxt += timedelta(days=1)
        return nxt
    return dt  # 'once' — no advance; it gets deactivated


class MissionScheduler:
    def __init__(self, repo=None):
        self._schedules: Dict[str, MissionSchedule] = {}
        self._loop_task: Optional[asyncio.Task] = None
        self._repo = repo   # ScheduleRepository | None

    async def load(self):
        """Rehydrate from the durable repository on startup."""
        if self._repo is None:
            return
        try:
            for s in await self._repo.all():
                self._schedules[s.schedule_id] = s
            if self._schedules:
                _log.info("scheduler: loaded %d schedule(s) from store", len(self._schedules))
        except Exception as e:
            _log.warning("scheduler: could not load schedules: %s", e)

    async def _persist(self, sched: MissionSchedule):
        if self._repo is not None:
            try:
                await self._repo.save(sched)
            except Exception as e:
                _log.warning("scheduler: persist failed for %s: %s", sched.schedule_id, e)

    # ---- CRUD ----
    async def add(self, sched: MissionSchedule) -> MissionSchedule:
        self._schedules[sched.schedule_id] = sched
        await self._persist(sched)
        return sched

    def get(self, sid: str) -> Optional[MissionSchedule]:
        return self._schedules.get(sid)

    def list(self) -> List[MissionSchedule]:
        return sorted(self._schedules.values(), key=lambda s: s.next_run)

    async def remove(self, sid: str) -> bool:
        existed = self._schedules.pop(sid, None) is not None
        if existed and self._repo is not None:
            try:
                await self._repo.delete(sid)
            except Exception as e:
                _log.warning("scheduler: delete failed for %s: %s", sid, e)
        return existed

    def clear(self):
        self._schedules.clear()

    # ---- firing ----
    def due(self, now: Optional[datetime] = None) -> List[MissionSchedule]:
        now = now or _utcnow()
        return [s for s in self._schedules.values()
                if s.active and s.next_run <= now]

    def mark_fired(self, sched: MissionSchedule, mission_id: str, now: Optional[datetime] = None):
        now = now or _utcnow()
        sched.last_run = now
        sched.run_count += 1
        sched.spawned_mission_ids.append(mission_id)
        if sched.cadence == "once":
            sched.active = False
        else:
            nxt = _advance(sched.next_run, sched.cadence)
            # don't fall behind if the process was asleep
            while nxt <= now:
                nxt = _advance(nxt, sched.cadence)
            sched.next_run = nxt

    async def run_due(self, spawn: Callable) -> List[str]:
        """spawn(goal, execution_mode) -> awaitable[mission_id]."""
        spawned: List[str] = []
        for sched in self.due():
            try:
                mission_id = await spawn(sched.goal, sched.execution_mode)
                self.mark_fired(sched, mission_id)
                await self._persist(sched)
                spawned.append(mission_id)
            except Exception as e:  # pragma: no cover
                _log.warning("scheduler: schedule %s failed: %s", sched.schedule_id, e)
        return spawned

    # ---- local background loop (Cloud Scheduler replaces this in prod) ----
    def start_loop(self, spawn: Callable, interval_s: int = 30):
        if self._loop_task and not self._loop_task.done():
            return

        async def _loop():
            while True:
                await asyncio.sleep(interval_s)
                try:
                    await self.run_due(spawn)
                except Exception as e:  # pragma: no cover
                    print(f"[scheduler] loop error: {e}")

        self._loop_task = asyncio.create_task(_loop())

    def stop_loop(self):
        if self._loop_task:
            self._loop_task.cancel()
            self._loop_task = None


def first_run_for(cadence: str, hour_utc: int, minute_utc: int,
                  now: Optional[datetime] = None) -> datetime:
    """Next occurrence of hour:minute UTC that matches the cadence."""
    now = now or _utcnow()
    candidate = now.replace(hour=hour_utc % 24, minute=minute_utc % 60,
                            second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    if cadence == "weekdays":
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
    return candidate
