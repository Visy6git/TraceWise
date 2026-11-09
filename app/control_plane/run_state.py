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


ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.READY_FOR_STAGE_1: {RunState.CLAIMS_RUNNING, RunState.CANCELLED},
    RunState.CLAIMS_RUNNING: {RunState.CLAIMS_AWAITING_REVIEW, RunState.FAILED, RunState.CANCELLED},
    RunState.CLAIMS_AWAITING_REVIEW: {RunState.CLAIMS_APPROVED, RunState.CHANGES_REQUESTED, RunState.CANCELLED},
    RunState.CLAIMS_APPROVED: {RunState.RULES_RUNNING, RunState.CANCELLED},
    RunState.RULES_RUNNING: {RunState.RULES_AWAITING_REVIEW, RunState.FAILED, RunState.CANCELLED},
    RunState.RULES_AWAITING_REVIEW: {RunState.RULES_APPROVED, RunState.CHANGES_REQUESTED, RunState.CANCELLED},
    RunState.RULES_APPROVED: {RunState.EVALUATION_RUNNING, RunState.CANCELLED},
    RunState.EVALUATION_RUNNING: {RunState.EVALUATION_AWAITING_REVIEW, RunState.FAILED, RunState.CANCELLED},
    RunState.EVALUATION_AWAITING_REVIEW: {RunState.COMPLETE, RunState.CHANGES_REQUESTED, RunState.CANCELLED},
    RunState.CHANGES_REQUESTED: {RunState.CLAIMS_RUNNING, RunState.RULES_RUNNING, RunState.EVALUATION_RUNNING, RunState.CANCELLED},
    RunState.COMPLETE: set(), RunState.CANCELLED: set(), RunState.FAILED: set(),
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
