"""Phase 22 — Mission Scheduler (ADR-069) and durable-approval long-running path."""
import asyncio
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient

from nexora.main import app
from nexora.core.scheduler import MissionScheduler, first_run_for, _advance
from packages.core.models import MissionSchedule


def _now():
    return datetime.now(timezone.utc)


def test_advance_cadences():
    d = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)   # a Monday
    assert _advance(d, "daily") == d + timedelta(days=1)
    assert _advance(d, "weekly") == d + timedelta(days=7)
    fri = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)
    assert _advance(fri, "weekdays").weekday() == 0        # Fri -> Mon


def test_first_run_is_in_the_future():
    nr = first_run_for("daily", 8, 0)
    assert nr > _now()


def test_scheduler_due_and_advance():
    s = MissionScheduler()
    past = MissionSchedule(goal="daily brief", cadence="daily",
                           next_run=_now() - timedelta(minutes=1))
    future = MissionSchedule(goal="later", cadence="daily",
                             next_run=_now() + timedelta(hours=5))
    asyncio.run(s.add(past)); asyncio.run(s.add(future))
    due = s.due()
    assert past in due and future not in due

    s.mark_fired(past, "mission-1")
    assert past.run_count == 1
    assert "mission-1" in past.spawned_mission_ids
    assert past.next_run > _now()          # advanced
    assert past not in s.due()


def test_once_schedule_deactivates_after_fire():
    s = MissionScheduler()
    once = MissionSchedule(goal="one time", cadence="once",
                           next_run=_now() - timedelta(seconds=1))
    asyncio.run(s.add(once))
    s.mark_fired(once, "m")
    assert once.active is False
    assert once not in s.due()


def test_scheduler_persists_and_reloads_from_repo():
    """Restart continuity: a schedule survives a fresh MissionScheduler."""
    from nexora.core.repository import InMemoryScheduleRepository
    repo = InMemoryScheduleRepository()
    s1 = MissionScheduler(repo)
    sched = MissionSchedule(goal="weekly review", cadence="weekly",
                            next_run=_now() + timedelta(days=1))
    asyncio.run(s1.add(sched))

    s2 = MissionScheduler(repo)          # simulates a process restart
    asyncio.run(s2.load())
    assert s2.get(sched.schedule_id) is not None
    assert s2.list()[0].goal == "weekly review"

    assert asyncio.run(s2.remove(sched.schedule_id)) is True
    s3 = MissionScheduler(repo)
    asyncio.run(s3.load())
    assert s3.get(sched.schedule_id) is None


def test_schedule_api_roundtrip_and_run_now():
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/api/v1/schedules", json={
                "goal": "Summarise my morning", "cadence": "weekdays",
                "hour_utc": 7, "execution_mode": "MOCK"})
            assert r.status_code == 200
            sid = r.json()["schedule_id"]

            r = await ac.get("/api/v1/schedules")
            assert any(s["schedule_id"] == sid for s in r.json())

            r = await ac.post(f"/api/v1/schedules/{sid}/run")
            assert r.status_code == 200
            assert r.json()["mission_id"]

            r = await ac.delete(f"/api/v1/schedules/{sid}")
            assert r.status_code == 200
    asyncio.run(_run())


def test_internal_endpoints_open_by_default_but_gate_when_audience_set():
    import os
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # default: no NEXORA_INTERNAL_AUDIENCE -> open
            r = await ac.post("/internal/run_due")
            assert r.status_code == 200
            # audience set -> a call with no token is rejected
            os.environ["NEXORA_INTERNAL_AUDIENCE"] = "https://nexora.example.run.app"
            try:
                r = await ac.post("/internal/run_due")
                assert r.status_code == 401
            finally:
                os.environ.pop("NEXORA_INTERNAL_AUDIENCE", None)
    asyncio.run(_run())


def test_run_due_endpoint_spawns_past_due():
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            await ac.post("/api/v1/schedules", json={
                "goal": "past due goal", "cadence": "once",
                "start_in_minutes": 0, "execution_mode": "MOCK"})
            r = await ac.post("/internal/run_due")
            assert r.status_code == 200
            assert r.json()["count"] >= 1
    asyncio.run(_run())
