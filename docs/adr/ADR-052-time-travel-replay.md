# ADR-052: Time-Travel DAG Reconstruction
Status: Accepted.

Decision: The replay scrubber reconstructs node statuses purely from the ordered event
log (NODE.STARTED→RUNNING, COMPLETED→SUCCESS, SKIPPED→SKIPPED, FAILED→FAILED,
APPROVAL_REQUESTED→WAITING_APPROVAL), never from live mission state. Playback is a
pure function of events[0..idx].

Consequences: Judges can scrub or auto-play any completed mission and watch the DAG
build up deterministically. No live providers are touched; replay is always safe.