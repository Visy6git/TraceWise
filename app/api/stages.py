"""Stages API router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from app.agents.claims_orchestrator.agent import run_claims_stage
from app.agents.evaluator_orchestrator.agent import run_evaluation_stage
from app.agents.rules_orchestrator.agent import run_rules_stage
from app.control_plane.run_state import RunState, validate_stage_start
from app.schemas.messages import StageName
from app.schemas.run import StageActionResponse, StageStartRequest
from app.services.database import default_run_repo

router = APIRouter(tags=["stages"])


@router.post("/runs/{run_id}/stages/{stage}/start", response_model=StageActionResponse)
def start_stage(run_id: str, stage: StageName, payload: StageStartRequest) -> StageActionResponse:
    run = default_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    current_state = RunState(run["status"])

    # Validate gate preconditions
    try:
        validate_stage_start(current_state, stage.value)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    # Move to running state
    running_states = {
        "claims": RunState.CLAIMS_RUNNING,
        "rules": RunState.RULES_RUNNING,
        "evaluation": RunState.EVALUATION_RUNNING,
    }
    default_run_repo.transition(
        run_id=run_id,
        expected_version=run["version"],
        new_state=running_states[stage.value],
        active_stage=stage.value,
    )

    # Run orchestrator
    try:
        if stage == StageName.claims:
            res = run_claims_stage(run_id, payload.expected_input_manifest_hash)
            msg = f"Claims stage completed: {res.get('total_claims')} claims extracted. Manifest: {res.get('stage_1_manifest_hash', '')[:8]}"
        elif stage == StageName.rules:
            res = run_rules_stage(run_id, payload.expected_input_manifest_hash)
            msg = f"Rules stage completed: {res.get('claims_processed')} claims synthesized. Manifest: {res.get('stage_2_manifest_hash', '')[:8]}"
        elif stage == StageName.evaluation:
            res = run_evaluation_stage(run_id)
            summ = res.get("summary", {})
            msg = f"Evaluation completed: {summ.get('passed')} passed, {summ.get('discrepancy')} discrepancy."
        else:
            raise ValueError(f"Unknown stage {stage}")

        updated_run = default_run_repo.get_run(run_id)
        return StageActionResponse(
            run_id=run_id,
            stage=stage,
            status=updated_run["status"],
            accepted=True,
            message=msg,
        )
    except Exception as e:
        # If execution failed, transition to FAILED
        cur = default_run_repo.get_run(run_id)
        try:
            default_run_repo.transition(
                run_id=run_id,
                expected_version=cur["version"],
                new_state=RunState.FAILED,
                active_stage=None,
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Stage execution error: {str(e)}")


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
