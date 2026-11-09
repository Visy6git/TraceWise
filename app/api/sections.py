"""Document structure API router."""
from __future__ import annotations

import json
from typing import Any
from fastapi import APIRouter
from app.schemas.section import SectionNode
from app.services.storage import default_storage

router = APIRouter(tags=["document structure"])


@router.get("/runs/{run_id}/sections", response_model=list[dict[str, Any]])
def get_sections(run_id: str) -> list[dict[str, Any]]:
    path = f"default/{run_id}/extracted/sections.json"
    try:
        content = default_storage.read_text(path)
        return json.loads(content)
    except Exception:
        return []
