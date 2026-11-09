"""Runs API router."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.config import MAX_UPLOAD_MB, MOCK_RUNS_ENABLED
from app.schemas.run import CreateRunRequest, RunSummary
from app.services.database import default_run_repo
from app.services.storage import default_storage

router = APIRouter(tags=["runs"])


@router.post("/runs", response_model=RunSummary, status_code=status.HTTP_201_CREATED)
def create_run(payload: CreateRunRequest) -> RunSummary:
    """Create a new run with immutable target report and source files."""
    if not MOCK_RUNS_ENABLED:
        raise HTTPException(
            status_code=409,
            detail="Live mode accepts uploaded file bytes through POST /api/runs/upload",
        )
    run_id = uuid.uuid4().hex

    target_id = payload.target_object_id
    source_ids = payload.source_object_ids

    if MOCK_RUNS_ENABLED and (target_id == "sample" or not Path(target_id).exists()):
        sample_doc = Path("runtime/sample_pbrer_data/PBRER_Annual_Report_2024_Nexipril.docx").resolve()
        if sample_doc.exists():
            target_id = str(sample_doc)

    if MOCK_RUNS_ENABLED and (
        not source_ids or source_ids == ["sample"] or not all(Path(s).exists() for s in source_ids)
    ):
        sample_dir = Path("runtime/sample_pbrer_data").resolve()
        if sample_dir.exists():
            source_ids = [str(p) for p in sample_dir.glob("*.xlsx")]

    if not target_id or not Path(target_id).is_file():
        raise HTTPException(status_code=400, detail="Target DOCX path does not exist")
    if not source_ids or not all(Path(source).is_file() for source in source_ids):
        raise HTTPException(status_code=400, detail="Every source path must exist")

    # Calculate input manifest hash
    hasher = hashlib.sha256()
    hasher.update(Path(target_id).read_bytes())
    for s in source_ids:
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
        stage_1_manifest_hash=run.get("stage_1_manifest_hash"),
        stage_2_manifest_hash=run.get("stage_2_manifest_hash"),
        stage_3_manifest_hash=run.get("stage_3_manifest_hash"),
        created_at=run["created_at"],
        version=run["version"],
    )


@router.post("/runs/upload", response_model=RunSummary, status_code=status.HTTP_201_CREATED)
async def upload_run(
    run_name: str = Form(..., min_length=1, max_length=160),
    target_file: UploadFile = File(...),
    source_files: list[UploadFile] = File(..., min_length=1),
    product_name: str | None = Form(default=None),
    reporting_period_start: str | None = Form(default=None),
    reporting_period_end: str | None = Form(default=None),
) -> RunSummary:
    """Create a run from actual DOCX and XLSX/CSV upload bytes."""
    if MOCK_RUNS_ENABLED:
        raise HTTPException(
            status_code=409,
            detail="Disable MOCK_RUNS_ENABLED before creating a live upload run",
        )

    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    upload_items = [(target_file, "target"), *((source, "source") for source in source_files)]
    staged: list[tuple[str, bytes]] = []
    for upload, role in upload_items:
        original_name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        suffix = Path(original_name).suffix.lower()
        allowed = {".docx"} if role == "target" else {".xlsx", ".csv"}
        if not original_name or suffix not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"{role.title()} files must use one of: {', '.join(sorted(allowed))}",
            )
        content = await upload.read(max_bytes + 1)
        if not content:
            raise HTTPException(status_code=400, detail=f"{original_name} is empty")
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{original_name} exceeds the {MAX_UPLOAD_MB} MB per-file limit",
            )
        staged.append((original_name, content))

    source_names = [name.casefold() for name, _ in staged[1:]]
    if len(source_names) != len(set(source_names)):
        raise HTTPException(status_code=400, detail="Source filenames must be unique within a run")

    run_id = uuid.uuid4().hex
    target_name, target_content = staged[0]
    target_stored = default_storage.put_immutable(
        tenant_id="default",
        run_id=run_id,
        logical_path=f"input/target/{target_name}",
        body=target_content,
    )
    source_ids: list[str] = []
    hasher = hashlib.sha256()
    hasher.update(target_content)
    for source_name, source_content in staged[1:]:
        stored = default_storage.put_immutable(
            tenant_id="default",
            run_id=run_id,
            logical_path=f"input/sources/{source_name}",
            body=source_content,
        )
        source_ids.append(str(stored["physical_path"]))
        hasher.update(source_content)

    run = default_run_repo.create_run(
        run_id=run_id,
        run_name=run_name,
        target_object_id=str(target_stored["physical_path"]),
        source_object_ids=source_ids,
        product_name=product_name,
        reporting_period_start=reporting_period_start,
        reporting_period_end=reporting_period_end,
        input_manifest_hash=hasher.hexdigest(),
    )
    return RunSummary(
        run_id=run["run_id"],
        run_name=run["run_name"],
        status=run["status"],
        active_stage=run.get("active_stage"),
        input_manifest_hash=run["input_manifest_hash"],
        stage_1_manifest_hash=run.get("stage_1_manifest_hash"),
        stage_2_manifest_hash=run.get("stage_2_manifest_hash"),
        stage_3_manifest_hash=run.get("stage_3_manifest_hash"),
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
        stage_1_manifest_hash=run.get("stage_1_manifest_hash"),
        stage_2_manifest_hash=run.get("stage_2_manifest_hash"),
        stage_3_manifest_hash=run.get("stage_3_manifest_hash"),
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
            stage_1_manifest_hash=r.get("stage_1_manifest_hash"),
            stage_2_manifest_hash=r.get("stage_2_manifest_hash"),
            stage_3_manifest_hash=r.get("stage_3_manifest_hash"),
            created_at=r["created_at"],
            version=r["version"],
        )
        for r in runs
    ]
