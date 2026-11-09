"""Document understanding: extract structure and scope the pipeline to Section 16.3."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.claims_orchestrator.section_scope import TARGET_SECTION, scope_to_section
from app.services.extraction import extract_target_report
from app.services.storage import default_storage


def build_full_document_model(target_file_path: str | Path, run_id: str) -> dict[str, Any]:
    """Extract the full document, then persist the Section 16.3 focused view.

    The full extraction is kept for debugging, while the APIs (``/sections`` and
    ``/document``) are served the 16.3 subtree so the whole workbench stays
    focused on Section 16.3.
    """
    doc_data = extract_target_report(target_file_path)

    # Full extraction (debug / provenance).
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
            "Confirm the target is a PBRER whose Section 16.3 (Evaluation of Risks "
            "and New Information) is present."
        )

    # Focused view served to the UI: the 16.3 subtree only.
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
