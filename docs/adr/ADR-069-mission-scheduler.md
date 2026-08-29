# ADR-069: Mission Scheduler — standing instructions over days and weeks

Status: Accepted.

## Context

The Taskmaster brief rewards agents that carry a task over hours, days, or
weeks. NEXORA missions complete in ~1-2 minutes; its "long-running" behaviour so
far was only the human-approval pause (a mission can sit `BLOCKED` indefinitely).
That is real but invisible in a demo.

## Decision

Add `MissionSchedule` (`packages/core/models.py`) and `MissionScheduler`
(`nexora/core/scheduler.py`): a goal + a cadence (`once`, `daily`, `weekdays`,
`weekly`, `monthly`) + a UTC time-of-day. `due()` returns schedules whose
`next_run` has passed; firing spawns a normal mission and rolls `next_run`
forward.

Two drivers, same code:

- **Local / single instance** — a background `asyncio` loop (`start_loop`) checks
  every 30 s. Enabled unless `NEXORA_DISPATCHER=cloud`.
- **Production** — **Cloud Scheduler** pings `POST /internal/run_due` every
  minute (Terraform `google_cloud_scheduler_job`, OIDC-authed).

API: `POST/GET/DELETE /api/v1/schedules`, `POST /api/v1/schedules/{id}/run`
(fire now), `POST /internal/run_due`.

## Consequences

- A NEXORA task can now genuinely span weeks — "every weekday at 07:00, brief me
  on my inbox and calendar" exists as a standing instruction; the Monday mission
  does not exist until Monday.
- Adds Cloud Scheduler to the deployed Google Cloud surface.
- Schedules are held in memory for now (like missions pre-Firestore); a Firestore
  collection is the obvious next step and mirrors `FirestoreMissionRepository`.
