"""Reviewer-gated state transition rules for the durable run state machine.

The transition validator is real and testable. Persistence/locking is a TODO: the next
agent should place this behind PostgreSQL transactions with a row-level lock or compare-
and-swap version check. Never trust agent-produced status strings as authority.
"""
from enum import StrEnum


class RunState(StrEnum):
    READY_FOR_STAGE_1 = "READY_FOR_STAGE_1"
    CLAIMS_RUNNING = "CLAIMS_RUNNING"
    CLAIMS_AWAITING_REVIEW = "CLAIMS_AWAITING_REVIEW"
    CLAIMS_APPROVED = "CLAIMS_APPROVED"
    RULES_RUNNING = "RULES_RUNNING"
    RULES_AWAITING_REVIEW = "RULES_AWAITING_REVIEW"
    RULES_APPROVED = "RULES_APPROVED"
    EVALUATION_RUNNING = "EVALUATION_RUNNING"
    EVALUATION_AWAITING_REVIEW = "EVALUATION_AWAITING_REVIEW"
    COMPLETE = "COMPLETE"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.READY_FOR_STAGE_1: {RunState.CLAIMS_RUNNING, RunState.CANCELLED},
    # A RUNNING stage can be paused mid-flight (cooperative) and later resumed.
    RunState.CLAIMS_RUNNING: {RunState.CLAIMS_AWAITING_REVIEW, RunState.FAILED, RunState.PAUSED, RunState.CANCELLED},
    # AWAITING_REVIEW states may re-enter their own RUNNING state to rerun the stage.
    RunState.CLAIMS_AWAITING_REVIEW: {RunState.CLAIMS_APPROVED, RunState.CLAIMS_RUNNING, RunState.CHANGES_REQUESTED, RunState.CANCELLED},
    RunState.CLAIMS_APPROVED: {RunState.CLAIMS_RUNNING, RunState.RULES_RUNNING, RunState.CANCELLED},
    RunState.RULES_RUNNING: {RunState.RULES_AWAITING_REVIEW, RunState.FAILED, RunState.PAUSED, RunState.CANCELLED},
    RunState.RULES_AWAITING_REVIEW: {RunState.RULES_APPROVED, RunState.RULES_RUNNING, RunState.CHANGES_REQUESTED, RunState.CANCELLED},
    RunState.RULES_APPROVED: {RunState.RULES_RUNNING, RunState.EVALUATION_RUNNING, RunState.CANCELLED},
    RunState.EVALUATION_RUNNING: {RunState.EVALUATION_AWAITING_REVIEW, RunState.FAILED, RunState.PAUSED, RunState.CANCELLED},
    RunState.EVALUATION_AWAITING_REVIEW: {RunState.COMPLETE, RunState.EVALUATION_RUNNING, RunState.CHANGES_REQUESTED, RunState.CANCELLED},
    RunState.CHANGES_REQUESTED: {RunState.CLAIMS_RUNNING, RunState.RULES_RUNNING, RunState.EVALUATION_RUNNING, RunState.CANCELLED},
    # A FAILED run is recoverable: the operator may rerun the stage that failed
    # without recreating the run or restarting from Stage 1.
    RunState.FAILED: {RunState.CLAIMS_RUNNING, RunState.RULES_RUNNING, RunState.EVALUATION_RUNNING, RunState.CANCELLED},
    # A PAUSED run resumes into the RUNNING state of the stage it was paused on.
    RunState.PAUSED: {RunState.CLAIMS_RUNNING, RunState.RULES_RUNNING, RunState.EVALUATION_RUNNING, RunState.CANCELLED},
    RunState.COMPLETE: {RunState.EVALUATION_RUNNING}, RunState.CANCELLED: set(),
}


class InvalidTransition(ValueError):
    pass


def validate_transition(current: RunState, target: RunState) -> None:
    """Reject any transition not explicitly present in the state graph."""
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(f"Transition {current.value} -> {target.value} is not allowed")


def validate_stage_start(state: RunState, stage: str, *, rework_stage: str | None = None) -> None:
    """Start a normal stage after its predecessor approval, or an explicitly reopened stage.

    `rework_stage` must be supplied by a durable, reviewer-authored rework decision; callers
    must not infer it from agent output or accept arbitrary browser input.
    """
    required = {
        "claims": RunState.READY_FOR_STAGE_1,
        "rules": RunState.CLAIMS_APPROVED,
        "evaluation": RunState.RULES_APPROVED,
    }
    if stage not in required:
        raise ValueError(f"Unknown stage: {stage}")
    if state == RunState.CHANGES_REQUESTED:
        if rework_stage != stage:
            raise InvalidTransition("Changes requested: start only the exact stage explicitly reopened by the reviewer")
    elif state != required[stage]:
        raise InvalidTransition(f"Stage {stage} requires state {required[stage].value}; current state is {state.value}")
    next_state = {"claims": RunState.CLAIMS_RUNNING, "rules": RunState.RULES_RUNNING, "evaluation": RunState.EVALUATION_RUNNING}[stage]
    validate_transition(state, next_state)


_STAGE_RUNNING_STATE = {
    "claims": RunState.CLAIMS_RUNNING,
    "rules": RunState.RULES_RUNNING,
    "evaluation": RunState.EVALUATION_RUNNING,
}

# A stage may be rerun from its own approval boundary or awaiting-review state, from
# reviewer-requested rework, after it FAILED, or after it was PAUSED mid-run (resume).
_RERUNNABLE_FROM = {
    "claims": {
        RunState.CLAIMS_AWAITING_REVIEW, RunState.CLAIMS_APPROVED,
        RunState.CHANGES_REQUESTED, RunState.FAILED, RunState.PAUSED,
    },
    "rules": {
        RunState.RULES_AWAITING_REVIEW, RunState.RULES_APPROVED,
        RunState.CHANGES_REQUESTED, RunState.FAILED, RunState.PAUSED,
    },
    "evaluation": {
        RunState.EVALUATION_AWAITING_REVIEW, RunState.COMPLETE,
        RunState.CHANGES_REQUESTED, RunState.FAILED, RunState.PAUSED,
    },
}


def validate_stage_rerun(
    state: RunState,
    stage: str,
    *,
    failed_stage: str | None = None,
    rework_stage: str | None = None,
) -> None:
    """Allow rerunning the stage at its approval boundary, or resuming/reworking it.

    Approved stages can be rerun only at their own boundary (before the next stage
    has started), except Stage 3, which can be rerun from COMPLETE. This avoids
    invalidating already-approved downstream outputs. The run must be reviewed again.
    `failed_stage`/`rework_stage` must come from durable metadata, not browser input.
    """
    if stage not in _STAGE_RUNNING_STATE:
        raise ValueError(f"Unknown stage: {stage}")
    if state not in _RERUNNABLE_FROM[stage]:
        raise InvalidTransition(
            f"Stage {stage} cannot be rerun from state {state.value}; "
            "rerun is allowed only at its approval boundary, after failure/pause, "
            "or while it awaits review"
        )
    # For FAILED and PAUSED runs, `failed_stage` carries the stage recorded as active;
    # only that stage can be resumed/rerun.
    if state in {RunState.FAILED, RunState.PAUSED} and failed_stage is not None and failed_stage != stage:
        raise InvalidTransition(
            f"Only the stage recorded as active ({failed_stage}) can be rerun, not {stage}"
        )
    if state == RunState.CHANGES_REQUESTED and rework_stage != stage:
        raise InvalidTransition(
            "Changes requested: rerun only the exact stage explicitly reopened by the reviewer"
        )
    validate_transition(state, _STAGE_RUNNING_STATE[stage])


def validate_stage_pause(state: RunState, stage: str) -> None:
    """Allow pausing only the stage that is currently running."""
    if stage not in _STAGE_RUNNING_STATE:
        raise ValueError(f"Unknown stage: {stage}")
    if state != _STAGE_RUNNING_STATE[stage]:
        raise InvalidTransition(
            f"Stage {stage} can only be paused while it is running; current state is {state.value}"
        )
    validate_transition(state, RunState.PAUSED)
