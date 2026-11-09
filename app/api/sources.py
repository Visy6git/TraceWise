"""Sources and Knowledge API router."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.database import default_run_repo
from app.services.storage import default_storage

router = APIRouter(tags=["sources"])


@router.get("/runs/{run_id}/sources")
def list_sources(run_id: str) -> list[dict[str, Any]]:
    path = f"default/{run_id}/extracted/source_extraction_manifest.json"
    try:
        content = default_storage.read_text(path)
        manifest = json.loads(content)
        return [
            {key: value for key, value in source.items() if key != "physical_path"}
            for source in manifest.get("sources", [])
        ]
    except FileNotFoundError:
        run = default_run_repo.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        sources = []
        for source_path in run.get("source_object_ids", []):
            source = Path(source_path)
            if not source.is_file():
                raise HTTPException(
                    status_code=404,
                    detail=f"Run source file is missing: {source.name}",
                )
            sources.append({
                "source_id": source.stem,
                "original_filename": source.name,
                "format": source.suffix.lstrip(".").lower(),
                "sha256": default_storage.compute_sha256(source.read_bytes()),
                "size_bytes": source.stat().st_size,
                "extraction_status": "pending",
                "limitations": [],
            })
        return sources
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Stored source manifest is invalid") from exc


@router.get("/runs/{run_id}/document")
def get_document_blocks(run_id: str) -> dict[str, Any]:
    path = f"default/{run_id}/extracted/target_document_blocks.json"
    try:
        return {"blocks": json.loads(default_storage.read_text(path))}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Run target has not been extracted yet")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Stored target extraction is invalid") from exc


@router.get("/runs/{run_id}/stage-1/source-knowledge")
def get_source_knowledge(run_id: str) -> dict[str, Any]:
    path = f"default/{run_id}/stage_1_claims/source_knowledge.json"
    try:
        content = default_storage.read_text(path)
        knowledge = json.loads(content)
        knowledge["sources"] = [
            {key: value for key, value in source.items() if key != "physical_path"}
            for source in knowledge.get("sources", [])
        ]
        knowledge["columns"] = [
            {
                key: value
                for key, value in column.items()
                if key not in {"sample_values", "min_value", "max_value"}
            }
            for column in knowledge.get("columns", [])
        ]
        return knowledge
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Source knowledge artifact not found. Run Stage 1 first.")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Stored source knowledge is invalid") from exc
