"""Evaluation API router (Stage 3 placeholder)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.database import default_eval_repo

router = APIRouter(tags=["evaluation"])


@router.get("/runs/{run_id}/stage-3/evaluation", response_model=dict[str, Any])
def get_evaluation(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "stage": "evaluation",
        "status": "placeholder",
        "is_placeholder": True,
        "message": (
            "Stage 3 (Independent Evaluation & Validation) is currently left as a placeholder."
        ),
        "results": default_eval_repo.list_evaluations(run_id),
    }
