"""Document inspection tools for Claims stage."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel

from app.services.storage import default_storage


class TargetBlockQuery(BaseModel):
    run_id: str
    section_id: str | None = None
    include_tables: bool = True
    limit: int = 100
    cursor: int = 0


def get_document_outline(query: TargetBlockQuery) -> list[dict[str, Any]]:
    # Look for extracted sections in storage
    outline_path = f"default/{query.run_id}/extracted/sections.json"
    try:
        content = default_storage.read_text(outline_path)
        sections = json.loads(content)
        return sections
    except Exception:
        return []


def get_target_blocks(query: TargetBlockQuery) -> dict[str, Any]:
    blocks_path = f"default/{query.run_id}/extracted/target_document_blocks.json"
    try:
        content = default_storage.read_text(blocks_path)
        all_blocks = json.loads(content)
    except Exception:
        all_blocks = []

    filtered = all_blocks
    if query.section_id:
        filtered = [b for b in filtered if b.get("section_id") == query.section_id]
    if not query.include_tables:
        filtered = [b for b in filtered if b.get("type") != "table"]

    start = query.cursor
    end = start + query.limit
    page = filtered[start:end]

    return {
        "run_id": query.run_id,
        "total_count": len(filtered),
        "cursor": end if end < len(filtered) else None,
        "blocks": page,
    }
