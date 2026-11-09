"""Evaluation API router."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter
from app.services.database import default_eval_repo

router = APIRouter(tags=["evaluation"])


@router.get("/runs/{run_id}/stage-3/evaluation", response_model=list[dict[str, Any]])
def get_evaluation(run_id: str) -> list[dict[str, Any]]:
    return default_eval_repo.list_evaluations(run_id)
