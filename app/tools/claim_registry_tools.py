"""Strands-facing Claim Registry wrapper."""
from __future__ import annotations

from typing import Any
from app.services.database import default_claim_repo


def list_claims(run_id: str, section_id: str | None = None) -> list[dict[str, Any]]:
    return default_claim_repo.list_claims(run_id, section_id=section_id)


def set_evidence_hint(run_id: str, claim_id: str, expected_version: int, hint: dict[str, Any]) -> dict[str, Any]:
    claim = default_claim_repo.get_claim(run_id, claim_id)
    if not claim:
        raise ValueError(f"Claim {claim_id} not found in run {run_id}")
    if claim["version"] != expected_version:
        raise ValueError(f"Stale claim version: expected {expected_version}, got {claim['version']}")

    patch = {"evidence_hint": hint}
    return default_claim_repo.update_claim_patch(
        run_id=run_id,
        claim_id=claim_id,
        expected_version=expected_version,
        patch=patch,
        reviewer_reason="Updated evidence hint from agent investigation",
        actor_id="claims-orchestrator",
    )


def validate_claim_register(run_id: str) -> dict[str, Any]:
    claims = list_claims(run_id)
    issues = []
    for c in claims:
        # Check quantitative claims have entity_unit
        c_type = c.get("claim_type")
        entity_unit = c.get("entity_unit")
        if c_type not in ("narrative_fact", "reconciliation", "other") and not entity_unit:
            issues.append(f"Claim {c['claim_id']} missing entity_unit")

        # Check evidence hint exists
        hint = c.get("evidence_hint")
        if not hint or not hint.get("text"):
            issues.append(f"Claim {c['claim_id']} missing evidence hint")

    return {
        "run_id": run_id,
        "valid": len(issues) == 0,
        "total_claims": len(claims),
        "issues": issues,
    }
