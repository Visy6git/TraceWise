"""Human review gates API router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from app.schemas.messages import StageName
from app.schemas.run import ReviewDecision, StageActionResponse
from app.services.database import default_run_repo

router = APIRouter(tags=["review"])


@router.post("/runs/{run_id}/stages/{stage}/review", response_model=StageActionResponse)
def review_stage(run_id: str, stage: StageName, decision: ReviewDecision) -> StageActionResponse:
    run = default_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    try:
        updated_run = default_run_repo.record_approval(
            run_id=run_id,
            stage=stage.value,
            reviewer_id="human_reviewer_1",
            decision=decision.decision,
            expected_version=run["version"],
            expected_manifest_hash=decision.expected_manifest_hash,
            reviewer_note=decision.reviewer_note,
            reviewer_role="reviewer",
        )
        return StageActionResponse(
            run_id=run_id,
            stage=stage,
            status=updated_run["status"],
            accepted=True,
            message=f"Review decision '{decision.decision}' recorded successfully.",
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
