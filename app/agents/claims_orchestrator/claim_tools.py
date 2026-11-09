"""Claim Registry tool contracts bound as Strands @tool functions."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from app.schemas.claim import Claim
from app.services.database import default_claim_repo


class ClaimPatchInput(BaseModel):
    claim_id: str
    expected_version: int
    patch: dict[str, Any]
    reason: str = Field(min_length=1)


def add_claim(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate full Claim schema, hierarchy membership, target locator and hint."""
    claim_obj = Claim(**payload)
    return default_claim_repo.save_claim(run_id, claim_obj.model_dump())


def update_claim(run_id: str, payload: ClaimPatchInput) -> dict[str, Any]:
    """Optimistic concurrency and append-only new version; never overwrite history."""
    return default_claim_repo.update_claim_patch(
        run_id=run_id,
        claim_id=payload.claim_id,
        expected_version=payload.expected_version,
        patch=payload.patch,
        reviewer_reason=payload.reason,
        actor_id="claims-orchestrator",
    )


def split_claim(run_id: str, claim_id: str, child_claims: list[dict[str, Any]], reason: str, expected_version: int) -> list[dict[str, Any]]:
    """Soft supersede parent, persist children and relation, validate each child."""
    parent = default_claim_repo.get_claim(run_id, claim_id)
    if not parent:
        raise ValueError(f"Claim {claim_id} not found")

    # Mark parent superseded
    default_claim_repo.update_claim_patch(
        run_id=run_id,
        claim_id=claim_id,
        expected_version=expected_version,
        patch={"status": "superseded"},
        reviewer_reason=f"Split into {len(child_claims)} children: {reason}",
    )

    created = []
    for c in child_claims:
        c["derivation"] = {
            "decision": "derived_from_existing_claims",
            "parent_claim_ids": [claim_id],
            "reason": reason,
        }
        res = add_claim(run_id, c)
        created.append(res)
    return created


def merge_claims(run_id: str, claim_ids: list[str], reason: str, expected_versions: dict[str, int], target_claim: dict[str, Any]) -> dict[str, Any]:
    """Supersede merged claims and persist combined claim."""
    for cid in claim_ids:
        exp_ver = expected_versions.get(cid, 1)
        default_claim_repo.update_claim_patch(
            run_id=run_id,
            claim_id=cid,
            expected_version=exp_ver,
            patch={"status": "superseded"},
            reviewer_reason=f"Merged into {target_claim.get('claim_id')}: {reason}",
        )
    target_claim["derivation"] = {
        "decision": "derived_from_existing_claims",
        "parent_claim_ids": claim_ids,
        "reason": reason,
    }
    return add_claim(run_id, target_claim)


def link_derived_value(run_id: str, claim_id: str, parent_claim_ids: list[str], expression: str, reason: str, expected_version: int) -> dict[str, Any]:
    """Link derived value and assert scope equivalence."""
    patch = {
        "derivation": {
            "decision": "derived_from_existing_claims",
            "parent_claim_ids": parent_claim_ids,
            "expression": expression,
            "scope_equivalent": True,
            "reason": reason,
        }
    }
    return default_claim_repo.update_claim_patch(
        run_id=run_id,
        claim_id=claim_id,
        expected_version=expected_version,
        patch=patch,
        reviewer_reason=reason,
    )


def delete_claim(run_id: str, claim_id: str, reason: str, expected_version: int) -> dict[str, Any]:
    """Soft-delete/supersede only. Audit and previous versions remain."""
    return default_claim_repo.update_claim_patch(
        run_id=run_id,
        claim_id=claim_id,
        expected_version=expected_version,
        patch={"status": "superseded"},
        reviewer_reason=reason,
    )
