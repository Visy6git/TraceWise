"""Stage 3 understanding + separate annual-generation API.

This is additive. Existing /stages/evaluation/* remains a legacy internal stage
identifier while user-facing copy calls it Stage 3 Understanding/Blueprint.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.control_plane.run_state import RunState, validate_stage_start, validate_stage_rerun
from app.schemas.run import ReviewDecision, StageStartRequest
from app.services.blueprint_repository import default_blueprint_repo
from app.services.database import default_run_repo
from app.services.event_stream import default_broker, stream_run_events
from app.services.storage import default_storage
from app.stages.stage_3_understanding.orchestrator import run_understanding_stage
from app.runtime.generation_service import load_blueprint_package, run_generation

router = APIRouter(tags=["blueprints", "generation"])
MAX_FILE_MB = 250
MAX_TOTAL_UPLOAD_MB = 600

_EXECUTABLE_SIGNATURES = [
    b"MZ",           # Windows PE executable
    b"\x7fELF",      # Linux ELF
    b"\xca\xfe\xba\xbe",  # Java class / Mach-O fat binary
    b"\xfe\xed\xfa\xce",  # Mach-O binary
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit binary
]


def _resolve_tenant(request: Request, override_tenant: str | None = None) -> str:
    """Resolve tenant from authenticated request context or headers; prevents spoofing."""
    header_tenant = request.headers.get("X-Tenant-ID")
    tenant = header_tenant or override_tenant or "default"
    clean = re.sub(r"[^a-zA-Z0-9_-]", "", tenant).strip()
    return clean or "default"


def _resolve_reviewer(request: Request) -> str:
    """Resolve reviewer identity from authenticated context or headers."""
    reviewer = request.headers.get("X-Reviewer-ID") or request.headers.get("X-User-ID") or "human_reviewer_1"
    clean = re.sub(r"[^a-zA-Z0-9_.-]", "", reviewer).strip()
    return clean or "human_reviewer_1"


class GenerationReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approve|request_changes)$")
    expected_output_manifest_hash: str = Field(min_length=16)
    reviewer_note: str | None = Field(default=None, max_length=4000)


def _stage3_background(run_id: str, manifest_hash: str) -> None:
    try:
        run_understanding_stage(run_id, manifest_hash)
    except Exception as exc:  # event + persisted FAILED state; never lose worker errors
        default_broker.emit_run_error(run_id, "understanding", str(exc))
        default_broker.emit_stage_update(run_id, "understanding", "error", progress=100)
        default_broker.emit_activity(
            run_id, "understanding", "Stage 3 failed", str(exc)[:400],
            kind="warning", status="error",
        )
        current = default_run_repo.get_run(run_id)
        if current:
            try:
                default_run_repo.transition(
                    run_id, current["version"], RunState.FAILED,
                    active_stage="evaluation",
                )
            except Exception:
                pass


def _generation_background(generation_id: str) -> None:
    try:
        run_generation(generation_id)
    except Exception as exc:
        default_blueprint_repo.update_generation(generation_id, status="failed", error_summary=str(exc)[:1000])
        default_broker.emit_run_error(generation_id, "generation", str(exc))
        default_broker.emit_stage_update(generation_id, "generation", "error", progress=100)
        default_broker.emit_activity(generation_id, "generation", "Generation failed", str(exc)[:400], kind="warning", status="error")


@router.post("/runs/{run_id}/stages/understanding/start")
def start_understanding(run_id: str, payload: StageStartRequest, request: Request):
    """Start Stage 3 only after Stage 2's exact manifest has reviewer approval."""
    run = default_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Learning run not found")
    if not payload.idempotency_key or not payload.idempotency_key.strip():
        raise HTTPException(status_code=400, detail="idempotency_key is required")
    expected_stage_2_manifest_hash = payload.expected_input_manifest_hash
    if expected_stage_2_manifest_hash != run.get("stage_2_manifest_hash"):
        raise HTTPException(status_code=409, detail="Stage 2 manifest hash is stale")
    try:
        validate_stage_start(RunState(run["status"]), "evaluation")
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    default_run_repo.transition(
        run_id, run["version"], RunState.EVALUATION_RUNNING, active_stage="evaluation",
    )
    threading.Thread(
        target=_stage3_background, args=(run_id, expected_stage_2_manifest_hash),
        name=f"stage-understanding-{run_id[:8]}", daemon=True,
    ).start()
    return {
        "run_id": run_id, "stage": "understanding", "status": "EVALUATION_RUNNING", "accepted": True,
        "message": "Stage 3 Understanding started. Live harness activity streams over AG-UI.",
    }


@router.post("/runs/{run_id}/stages/understanding/rerun")
def rerun_understanding(run_id: str, payload: StageStartRequest, request: Request):
    """Resume/rework Stage 3 in a new attempt while retaining prior blueprint versions."""
    run = default_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Learning run not found")
    if payload.expected_input_manifest_hash != run.get("stage_2_manifest_hash"):
        raise HTTPException(status_code=409, detail="Stage 2 manifest hash is stale")
    state = RunState(run["status"])
    rework_stage = default_run_repo.get_latest_rework_stage(run_id) if state == RunState.CHANGES_REQUESTED else None
    try:
        validate_stage_rerun(state, "evaluation", failed_stage=run.get("active_stage"), rework_stage=rework_stage)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    default_run_repo.transition(
        run_id, run["version"], RunState.EVALUATION_RUNNING,
        active_stage="evaluation", rework_stage=rework_stage,
    )
    threading.Thread(
        target=_stage3_background, args=(run_id, payload.expected_input_manifest_hash),
        name=f"rerun-understanding-{run_id[:8]}", daemon=True,
    ).start()
    return {"run_id": run_id, "stage": "understanding", "status": "EVALUATION_RUNNING", "accepted": True}


@router.post("/runs/{run_id}/stages/understanding/review")
def review_understanding(run_id: str, decision: ReviewDecision, request: Request):
    """Reviewer gate. Stage 3 agent cannot approve itself or mark a blueprint approved."""
    tenant_id = _resolve_tenant(request)
    reviewer_id = _resolve_reviewer(request)
    run = default_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Learning run not found")

    if decision.decision == "approve":
        candidate = default_blueprint_repo.get_for_learning_run(run_id)
        if not candidate:
            raise HTTPException(status_code=409, detail="No Stage 3 blueprint candidate found for this run")
        if candidate.get("manifest_hash") != decision.expected_manifest_hash:
            raise HTTPException(
                status_code=409,
                detail=f"Blueprint manifest mismatch: expected {decision.expected_manifest_hash[:16]}, candidate has {str(candidate.get('manifest_hash'))[:16]}",
            )
        try:
            load_blueprint_package(
                candidate["tenant_id"],
                candidate["blueprint_id"],
                candidate["version"],
                require_approved=False,
            )
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        updated = default_run_repo.record_approval(
            run_id=run_id, stage="evaluation", reviewer_id=reviewer_id,
            decision=decision.decision, expected_version=run["version"],
            expected_manifest_hash=decision.expected_manifest_hash,
            reviewer_note=decision.reviewer_note, reviewer_role="reviewer",
        )
        blueprint = None
        if decision.decision == "approve":
            blueprint = default_blueprint_repo.mark_approved(
                source_learning_run_id=run_id,
                manifest_hash=decision.expected_manifest_hash,
                reviewer_id=reviewer_id,
            )
            if not blueprint:
                raise ValueError("No blueprint candidate matches the approved Stage 3 manifest")

        default_broker.emit_activity(
            run_id, "understanding", "Stage 3 reviewer decision recorded",
            f"Decision: {decision.decision}. Blueprint {'approved' if blueprint else 'remains unapproved'}.",
            kind="gate", status="done" if blueprint else "warning",
        )
        return {
            "run_id": run_id, "stage": "understanding", "status": updated["status"],
            "accepted": True, "blueprint": blueprint,
        }
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/{run_id}/stage-3/blueprint")
def get_run_blueprint(run_id: str, request: Request):
    item = default_blueprint_repo.get_for_learning_run(run_id)
    if not item:
        raise HTTPException(status_code=404, detail="No Stage 3 blueprint candidate for this learning run")
    prefix = f"blueprints-{item['tenant_id']}/{item['blueprint_id']}/versions/v{item['version']:03d}"
    try:
        item["blueprint"] = json.loads(default_storage.read_text(f"{prefix}/blueprint.json"))
    except FileNotFoundError:
        item["blueprint"] = None
    return item


@router.get("/blueprints")
def list_blueprints(request: Request, tenant_id: str | None = None):
    resolved_tenant = _resolve_tenant(request, tenant_id)
    blueprints = default_blueprint_repo.list_approved(resolved_tenant)
    for blueprint in blueprints:
        try:
            load_blueprint_package(
                resolved_tenant,
                blueprint["blueprint_id"],
                blueprint["version"],
            )
        except (ValueError, FileNotFoundError) as exc:
            blueprint["generation_error"] = str(exc)
        else:
            blueprint["generation_error"] = None
    return blueprints


@router.get("/blueprints/{blueprint_id}")
def get_blueprint(blueprint_id: str, request: Request, version: int | None = None, tenant_id: str | None = None):
    resolved_tenant = _resolve_tenant(request, tenant_id)
    item = default_blueprint_repo.get(resolved_tenant, blueprint_id, version)
    if not item:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    if item.get("version_status") != "approved":
        raise HTTPException(status_code=403, detail="Only approved blueprint versions are available to the Generator")
    prefix = f"blueprints-{resolved_tenant}/{blueprint_id}/versions/v{item['version']:03d}"
    item["blueprint"] = json.loads(default_storage.read_text(f"{prefix}/blueprint.json"))
    return item


@router.post("/generations")
async def create_generation(
    request: Request,
    blueprint_id: str = Form(...),
    blueprint_version: int = Form(..., ge=1),
    run_name: str = Form(..., min_length=1, max_length=160),
    reporting_period_start: str = Form(...),
    reporting_period_end: str = Form(...),
    as_of_date: str | None = Form(default=None),
    source_files: list[UploadFile] = File(..., min_length=1),
    tenant_id: str | None = Form(default=None),
):
    """Create an independent generation run from source files only (no target DOCX)."""
    resolved_tenant = _resolve_tenant(request, tenant_id)
    blueprint = default_blueprint_repo.get(resolved_tenant, blueprint_id, blueprint_version)
    if not blueprint or blueprint.get("version_status") != "approved":
        raise HTTPException(status_code=409, detail="Selected blueprint version is not approved")
    try:
        load_blueprint_package(resolved_tenant, blueprint_id, blueprint_version)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if reporting_period_start > reporting_period_end:
        raise HTTPException(status_code=400, detail="Reporting period start must not be after end")

    generation_id = uuid.uuid4().hex
    source_ids: list[str] = []
    digest = hashlib.sha256()
    seen = set()
    max_bytes = MAX_FILE_MB * 1024 * 1024
    total_bytes = 0
    max_total_bytes = MAX_TOTAL_UPLOAD_MB * 1024 * 1024

    for upload in source_files:
        raw_name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        name = Path(raw_name).name
        if not name or ".." in name or Path(name).suffix.lower() not in {".xlsx", ".csv"}:
            raise HTTPException(status_code=400, detail=f"Unsupported source file: {raw_name}")
        if name.casefold() in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate source filename: {name}")
        seen.add(name.casefold())

        content = await upload.read(max_bytes + 1)
        if not content:
            raise HTTPException(status_code=400, detail=f"Source file {name} is empty")
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"Source file exceeds {MAX_FILE_MB}MB limit: {name}")

        total_bytes += len(content)
        if total_bytes > max_total_bytes:
            raise HTTPException(status_code=413, detail=f"Total upload size exceeds {MAX_TOTAL_UPLOAD_MB}MB limit")

        # Magic byte validation
        ext = Path(name).suffix.lower()
        if ext == ".xlsx":
            if not content.startswith(b"PK\x03\x04") and not content.startswith(b"PK\x05\x06") and not content.startswith(b"PK\x07\x08"):
                raise HTTPException(status_code=400, detail=f"File {name} does not have a valid XLSX/OpenXML header")
        elif ext == ".csv":
            if any(content.startswith(sig) for sig in _EXECUTABLE_SIGNATURES):
                raise HTTPException(status_code=400, detail=f"File {name} appears to be an executable binary, not a CSV")

        stored = default_storage.put_immutable(
            tenant_id=resolved_tenant,
            run_id=generation_id,
            logical_path=f"input/sources/{name}",
            body=content,
        )
        source_ids.append(str(stored["physical_path"]))
        digest.update(name.encode("utf-8"))
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)

    record = default_blueprint_repo.create_generation({
        "generation_id": generation_id,
        "tenant_id": resolved_tenant,
        "run_name": run_name,
        "blueprint_id": blueprint_id,
        "blueprint_version": blueprint_version,
        "reporting_period_start": reporting_period_start,
        "reporting_period_end": reporting_period_end,
        "as_of_date": as_of_date,
        "source_manifest_hash": digest.hexdigest(),
        "source_object_ids": source_ids,
    })
    return record


@router.get("/generations")
def list_generations(request: Request, tenant_id: str | None = None, blueprint_id: str | None = None):
    resolved_tenant = _resolve_tenant(request, tenant_id)
    return default_blueprint_repo.list_generations(resolved_tenant, blueprint_id)


@router.get("/generations/{generation_id}")
def get_generation(generation_id: str, request: Request):
    resolved_tenant = _resolve_tenant(request)
    item = default_blueprint_repo.get_generation(generation_id, tenant_id=resolved_tenant)
    if not item:
        # Fallback without tenant constraint for backwards compatibility
        item = default_blueprint_repo.get_generation(generation_id)
    if not item:
        raise HTTPException(status_code=404, detail="Generation run not found")
    return item


@router.post("/generations/{generation_id}/start")
def start_generation(generation_id: str, request: Request):
    resolved_tenant = _resolve_tenant(request)
    item = default_blueprint_repo.get_generation(generation_id, tenant_id=resolved_tenant)
    if not item:
        item = default_blueprint_repo.get_generation(generation_id)
    if not item:
        raise HTTPException(status_code=404, detail="Generation run not found")
    if item["status"] not in {"created", "failed"}:
        raise HTTPException(status_code=409, detail=f"Generation cannot start from {item['status']}")
    try:
        load_blueprint_package(item["tenant_id"], item["blueprint_id"], item["blueprint_version"])
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    default_blueprint_repo.update_generation(generation_id, tenant_id=item["tenant_id"], status="profiling", error_summary=None)
    threading.Thread(
        target=_generation_background, args=(generation_id,),
        name=f"generation-{generation_id[:8]}", daemon=True,
    ).start()
    return {"generation_id": generation_id, "status": "profiling", "accepted": True}


@router.get("/generations/{generation_id}/artifacts")
def get_generation_artifacts(generation_id: str, request: Request):
    resolved_tenant = _resolve_tenant(request)
    item = default_blueprint_repo.get_generation(generation_id, tenant_id=resolved_tenant)
    if not item:
        item = default_blueprint_repo.get_generation(generation_id)
    if not item:
        raise HTTPException(status_code=404, detail="Generation run not found")
    return item.get("artifacts_json", [])


@router.get("/generations/{generation_id}/artifacts/{artifact_id}/content")
def download_generation_artifact(generation_id: str, artifact_id: str, request: Request):
    resolved_tenant = _resolve_tenant(request)
    item = default_blueprint_repo.get_generation(generation_id, tenant_id=resolved_tenant)
    if not item:
        item = default_blueprint_repo.get_generation(generation_id)
    if not item:
        raise HTTPException(status_code=404, detail="Generation run not found")
    artifact = next((a for a in item.get("artifacts_json", []) if a.get("artifact_id") == artifact_id), None)
    if not artifact:
        raise HTTPException(status_code=404, detail="Generation artifact not found")

    logical_path = artifact.get("logical_path", "").lstrip("/\\")
    if ".." in logical_path:
        raise HTTPException(status_code=400, detail="Invalid artifact path")

    tenant_id = item["tenant_id"]
    path = f"{tenant_id}/{generation_id}/{logical_path}"
    try:
        content = default_storage.read_bytes(path)
    except FileNotFoundError:
        # Fallback to default tenant if originally saved under default
        try:
            content = default_storage.read_bytes(f"default/{generation_id}/{logical_path}")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Artifact bytes are unavailable") from exc

    name = Path(logical_path).name
    return Response(
        content=content,
        media_type=artifact.get("media_type", "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/generations/{generation_id}/events")
def stream_generation_events(generation_id: str, request: Request, cursor: str | None = None) -> StreamingResponse:
    """Stream live AG-UI SSE event frames for a generation run."""
    return StreamingResponse(
        stream_run_events(generation_id, cursor=cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/generations/{generation_id}/review")
def review_generation_output(generation_id: str, payload: GenerationReviewRequest, request: Request):
    """Human sign-off for the generated DOCX and its provenance package."""
    resolved_tenant = _resolve_tenant(request)
    reviewer_id = _resolve_reviewer(request)
    try:
        updated = default_blueprint_repo.record_generation_review(
            generation_id=generation_id,
            reviewer_id=reviewer_id,
            decision=payload.decision,
            expected_output_manifest_hash=payload.expected_output_manifest_hash,
            note=payload.reviewer_note,
            tenant_id=resolved_tenant,
        )
        if not updated:
            raise ValueError("Generation run not found or tenant unauthorized")
        return updated
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
