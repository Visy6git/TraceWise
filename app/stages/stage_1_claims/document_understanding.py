"""Document understanding: extract target DOCX and scope to Section 16.3."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.extraction import extract_target_report
from app.services.storage import default_storage
from app.stages.stage_1_claims.section_scope import TARGET_SECTION, scope_to_section


def build_full_document_model(target_file_path: str | Path, run_id: str) -> dict[str, Any]:
    doc_data = extract_target_report(target_file_path)

    default_storage.put_derived(
        tenant_id="default",
        run_id=run_id,
        logical_path="extracted/target_document_blocks_full.json",
        body=json.dumps(doc_data["blocks"], indent=2),
    )
    default_storage.put_derived(
        tenant_id="default",
        run_id=run_id,
        logical_path="extracted/sections_full.json",
        body=json.dumps(doc_data["sections"], indent=2),
    )

    scope = scope_to_section(doc_data, TARGET_SECTION)
    if scope is None:
        raise ValueError(
            f"Section {TARGET_SECTION} was not found in {doc_data['filename']}. "
            "Confirm the target document contains Section 16.3."
        )

    default_storage.put_derived(
        tenant_id="default",
        run_id=run_id,
        logical_path="extracted/sections.json",
        body=json.dumps(scope["subtree_sections"], indent=2),
    )
    default_storage.put_derived(
        tenant_id="default",
        run_id=run_id,
        logical_path="extracted/target_document_blocks.json",
        body=json.dumps(scope["scoped_blocks"], indent=2),
    )

    doc_data["scope"] = scope
    return doc_data

