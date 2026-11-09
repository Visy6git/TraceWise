"""Stages API router."""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException, status

from app.agents.claims_orchestrator.agent import run_claims_stage
from app.agents.evaluator_orchestrator.agent import run_evaluation_stage
from app.agents.rules_orchestrator.agent import run_rules_stage
from app.control_plane.run_state import RunState, validate_stage_start
from app.schemas.messages import StageName
from app.schemas.run import StageActionResponse, StageStartRequest
from app.services.database import default_run_repo
from app.services.event_stream import default_broker
from app.services.logging_config import get_run_logger

router = APIRouter(tags=["stages"])

_STAGE_RUNNERS = {
    "claims": run_claims_stage,
    "rules": run_rules_stage,
    "evaluation": run_evaluation_stage,
}
_RUNNING_STATES = {
    "claims": RunState.CLAIMS_RUNNING,
    "rules": RunState.RULES_RUNNING,
    "evaluation": RunState.EVALUATION_RUNNING,
}


def _execute_stage_background(run_id: str, stage: str, manifest: str) -> None:
    """Run an orchestrator off the request thread; stream progress and failures."""
    logger = get_run_logger(run_id, stage)
    try:
        runner = _STAGE_RUNNERS[stage]
        if stage == "evaluation":
            runner(run_id)
        else:
            runner(run_id, manifest)
    except Exception as exc:  # noqa: BLE001 - surface to the UI, never crash silently
        logger.exception("Stage %s failed for run %s", stage, run_id)
        default_broker.emit_stage_update(run_id, stage, "error", progress=100)
        default_broker.emit_run_error(run_id, stage, str(exc))
        default_broker.emit_activity(
            run_id=run_id, stage=stage, title=f"{stage.title()} stage failed",
            detail=str(exc)[:300], kind="warning", status="error",
        )
        cur = default_run_repo.get_run(run_id)
        if cur:
            try:
                default_run_repo.transition(
                    run_id=run_id, expected_version=cur["version"],
                    new_state=RunState.FAILED, active_stage=None,
                )
            except Exception:
                logger.exception("Could not transition run %s to FAILED", run_id)


@router.post("/runs/{run_id}/stages/{stage}/start", response_model=StageActionResponse)
def start_stage(run_id: str, stage: StageName, payload: StageStartRequest) -> StageActionResponse:
    run = default_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    expected_manifest = (
        run.get("input_manifest_hash") if stage == StageName.claims
        else run.get("stage_1_manifest_hash") if stage == StageName.rules
        else run.get("stage_2_manifest_hash")
    )
    if not expected_manifest or payload.expected_input_manifest_hash != expected_manifest:
        raise HTTPException(status_code=409, detail="Stage input manifest is missing or stale")

    current_state = RunState(run["status"])

    # Validate gate preconditions (synchronous → immediate 4xx on violation).
    try:
        validate_stage_start(current_state, stage.value)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    # Move to running state, then execute asynchronously so the UI can stream
    # AG-UI events (subagent dispatch, tool calls, progress) while work runs.
    default_run_repo.transition(
        run_id=run_id,
        expected_version=run["version"],
        new_state=_RUNNING_STATES[stage.value],
        active_stage=stage.value,
    )

    thread = threading.Thread(
        target=_execute_stage_background,
        args=(run_id, stage.value, payload.expected_input_manifest_hash),
        name=f"stage-{stage.value}-{run_id[:8]}",
        daemon=True,
    )
    thread.start()

    updated_run = default_run_repo.get_run(run_id)
    return StageActionResponse(
        run_id=run_id,
        stage=stage,
        status=updated_run["status"],
        accepted=True,
        message=f"{stage.value.title()} stage started. Streaming live progress over AG-UI.",
    )


@router.post("/runs/{run_id}/stages/{stage}/cancel", response_model=StageActionResponse)
def cancel_stage(run_id: str, stage: StageName) -> StageActionResponse:
    run = default_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    default_run_repo.transition(
        run_id=run_id,
        expected_version=run["version"],
        new_state=RunState.CANCELLED,
        active_stage=None,
    )

    return StageActionResponse(
        run_id=run_id,
        stage=stage,
        status=RunState.CANCELLED.value,
        accepted=True,
        message="Stage cancelled by user request.",
    )
