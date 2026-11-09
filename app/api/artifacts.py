"""Artifacts API router."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter
from app.services.database import default_artifact_repo

router = APIRouter(tags=["artifacts"])


@router.get("/runs/{run_id}/artifacts", response_model=list[dict[str, Any]])
def list_artifacts(run_id: str) -> list[dict[str, Any]]:
    return default_artifact_repo.list_artifacts(run_id)


@router.get("/runs/{run_id}/claims/{claim_id}/artifacts", response_model=list[dict[str, Any]])
def list_claim_artifacts(run_id: str, claim_id: str) -> list[dict[str, Any]]:
    return default_artifact_repo.list_artifacts(run_id, claim_id=claim_id)
