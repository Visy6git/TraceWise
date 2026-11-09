"""Claims Registry API router."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, status
from app.schemas.claim import Claim, ClaimPatch
from app.services.database import default_claim_repo

router = APIRouter(tags=["claims"])


@router.get("/runs/{run_id}/stage-1/claims", response_model=list[dict[str, Any]])
def list_claims(run_id: str) -> list[dict[str, Any]]:
    claims = default_claim_repo.list_claims(run_id)
    return claims


@router.patch("/runs/{run_id}/stage-1/claims/{claim_id}", response_model=dict[str, Any])
def update_claim(run_id: str, claim_id: str, patch: ClaimPatch) -> dict[str, Any]:
    try:
        updated = default_claim_repo.update_claim_patch(
            run_id=run_id,
            claim_id=claim_id,
            expected_version=patch.expected_version,
            patch=patch.model_dump(exclude_unset=True),
            reviewer_reason=patch.reviewer_reason,
            actor_id="reviewer",
        )
        return updated
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
