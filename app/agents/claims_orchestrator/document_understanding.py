"""Document understanding pipeline implementation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.extraction import extract_target_report
from app.services.storage import default_storage


def build_full_document_model(target_file_path: str | Path, run_id: str) -> dict[str, Any]:
    """Extract document blocks and section hierarchy from target PBRER."""
    doc_data = extract_target_report(target_file_path)

    # Save extracted blocks and sections into storage
    blocks_json = json.dumps(doc_data["blocks"], indent=2)
    default_storage.put_immutable(
        tenant_id="default",
        run_id=run_id,
        logical_path="extracted/target_document_blocks.json",
        body=blocks_json,
    )

    sections_json = json.dumps(doc_data["sections"], indent=2)
    default_storage.put_immutable(
        tenant_id="default",
        run_id=run_id,
        logical_path="extracted/sections.json",
        body=sections_json,
    )

    return doc_data
