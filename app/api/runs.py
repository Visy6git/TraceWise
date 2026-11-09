"""Runs API router."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from app.schemas.run import CreateRunRequest, RunSummary
from app.services.database import default_run_repo

router = APIRouter(tags=["runs"])


@router.post("/runs", response_model=RunSummary, status_code=status.HTTP_201_CREATED)
def create_run(payload: CreateRunRequest) -> RunSummary:
    """Create a new run with immutable target report and source files."""
    run_id = uuid.uuid4().hex

    target_id = payload.target_object_id
    source_ids = payload.source_object_ids

    # Local convenience: if sample requested, wire to runtime/sample_pbrer_data
    if target_id == "sample" or not Path(target_id).exists():
        sample_doc = Path("runtime/sample_pbrer_data/PBRER_Annual_Report_2024_Nexipril.docx").resolve()
        if sample_doc.exists():
            target_id = str(sample_doc)

    if not source_ids or source_ids == ["sample"] or not all(Path(s).exists() for s in source_ids):
        sample_dir = Path("runtime/sample_pbrer_data").resolve()
        if sample_dir.exists():
            source_ids = [str(p) for p in sample_dir.glob("*.xlsx")]

    # Calculate input manifest hash
    hasher = hashlib.sha256()
    if target_id and Path(target_id).exists():
        hasher.update(Path(target_id).read_bytes())
    for s in source_ids:
        if Path(s).exists():
            hasher.update(Path(s).read_bytes())
    input_manifest_hash = hasher.hexdigest()

    run = default_run_repo.create_run(
        run_id=run_id,
        run_name=payload.run_name,
        target_object_id=target_id,
        source_object_ids=source_ids,
        product_name=payload.product_name or "Nexipril Sodium",
        reporting_period_start=payload.reporting_period_start or "2024-01-01",
        reporting_period_end=payload.reporting_period_end or "2024-12-31",
        input_manifest_hash=input_manifest_hash,
    )

    return RunSummary(
        run_id=run["run_id"],
        run_name=run["run_name"],
        status=run["status"],
        active_stage=run.get("active_stage"),
        input_manifest_hash=run["input_manifest_hash"],
        created_at=run["created_at"],
        version=run["version"],
    )


@router.get("/runs/{run_id}", response_model=RunSummary)
def get_run(run_id: str) -> RunSummary:
    run = default_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return RunSummary(
        run_id=run["run_id"],
        run_name=run["run_name"],
        status=run["status"],
        active_stage=run.get("active_stage"),
        input_manifest_hash=run["input_manifest_hash"],
        created_at=run["created_at"],
        version=run["version"],
    )


@router.get("/runs", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    runs = default_run_repo.list_runs()
    return [
        RunSummary(
            run_id=r["run_id"],
            run_name=r["run_name"],
            status=r["status"],
            active_stage=r.get("active_stage"),
            input_manifest_hash=r["input_manifest_hash"],
            created_at=r["created_at"],
            version=r["version"],
        )
        for r in runs
    ]
