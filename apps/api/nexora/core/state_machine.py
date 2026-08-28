from packages.core.models import MissionState

VALID_TRANSITIONS = {
    MissionState.CREATED: [MissionState.INTERPRETING],
    MissionState.INTERPRETING: [MissionState.PLANNING, MissionState.FAILED],
    MissionState.PLANNING: [MissionState.CRITICIZING, MissionState.FAILED],
    MissionState.CRITICIZING: [MissionState.EXECUTING, MissionState.FAILED],
    MissionState.EXECUTING: [MissionState.VERIFYING, MissionState.BLOCKED, MissionState.REPLANNING, MissionState.FAILED],
    MissionState.BLOCKED: [MissionState.EXECUTING, MissionState.VERIFYING, MissionState.REPLANNING, MissionState.FAILED],
    MissionState.REPLANNING: [MissionState.EXECUTING, MissionState.FAILED],
    MissionState.VERIFYING: [MissionState.REPLANNING, MissionState.EXECUTING, MissionState.COMPLETED, MissionState.PARTIAL_SUCCESS, MissionState.FAILED],
}

class InvalidStateTransitionError(Exception):
    pass

class MissionStateMachine:
    @staticmethod
    def transition(current: MissionState, next_state: MissionState) -> MissionState:
        if next_state not in VALID_TRANSITIONS.get(current, []):
            raise InvalidStateTransitionError(f"Invalid transition {current} -> {next_state}")
        return next_state