"""Artifacts API router."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.database import default_artifact_repo
from app.services.storage import default_storage

router = APIRouter(tags=["artifacts"])


@router.get("/runs/{run_id}/artifacts", response_model=list[dict[str, Any]])
def list_artifacts(run_id: str) -> list[dict[str, Any]]:
    return default_artifact_repo.list_artifacts(run_id)


@router.get("/runs/{run_id}/claims/{claim_id}/artifacts", response_model=list[dict[str, Any]])
def list_claim_artifacts(run_id: str, claim_id: str) -> list[dict[str, Any]]:
    return default_artifact_repo.list_artifacts(run_id, claim_id=claim_id)


@router.get("/runs/{run_id}/artifacts/{artifact_id}/content", response_model=dict[str, Any])
def get_artifact_content(run_id: str, artifact_id: str) -> dict[str, Any]:
    artifact = default_artifact_repo.get_artifact(run_id, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found for run {run_id}")
    logical_path = artifact["logical_path"]
    try:
        raw = default_storage.read_bytes(f"default/{run_id}/{logical_path}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Stored file for artifact {artifact_id} is missing") from exc
    return {
        "artifact_id": artifact["artifact_id"],
        "run_id": run_id,
        "stage": artifact["stage"],
        "claim_id": artifact.get("claim_id"),
        "logical_path": logical_path,
        "media_type": artifact["media_type"],
        "size_bytes": artifact["size_bytes"],
        "sha256": artifact["sha256"],
        "content": raw.decode("utf-8", errors="replace"),
    }
