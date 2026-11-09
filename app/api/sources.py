"""Sources and Knowledge API router."""
from __future__ import annotations

import json
from typing import Any
from fastapi import APIRouter, HTTPException
from app.services.storage import default_storage

router = APIRouter(tags=["sources"])


@router.get("/runs/{run_id}/sources")
def list_sources(run_id: str) -> list[dict[str, Any]]:
    path = f"default/{run_id}/extracted/source_extraction_manifest.json"
    try:
        content = default_storage.read_text(path)
        manifest = json.loads(content)
        return manifest.get("sources", [])
    except Exception:
        return []


@router.get("/runs/{run_id}/stage-1/source-knowledge")
def get_source_knowledge(run_id: str) -> dict[str, Any]:
    path = f"default/{run_id}/stage_1_claims/source_knowledge.json"
    try:
        content = default_storage.read_text(path)
        return json.loads(content)
    except Exception:
        raise HTTPException(status_code=404, detail="Source knowledge artifact not found. Run Stage 1 first.")
