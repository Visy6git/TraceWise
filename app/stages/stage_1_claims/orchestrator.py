"""Stage 1 Orchestrator: Extraction -> Per-File Harness Exploration -> Strands Claim Extraction."""
from __future__ import annotations

import hashlib
import json

from app.control_plane.run_state import RunState
from app.services.database import default_artifact_repo, default_claim_repo, default_run_repo
from app.services.event_stream import default_broker
from app.services.storage import default_storage
from app.stages.stage_1_claims.claim_extractor import extract_claims_by_subsection
from app.stages.stage_1_claims.document_understanding import build_full_document_model
from app.stages.stage_1_claims.source_explorer import explore_all_sources_with_harness


def run_claims_stage(run_id: str, expected_input_manifest_hash: str) -> dict:
    run = default_run_repo.get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    if run["input_manifest_hash"] != expected_input_manifest_hash:
        raise ValueError("Input manifest hash mismatch; run inputs changed unexpectedly")

    default_broker.emit_run_started(run_id, "claims")
    default_broker.emit_stage_update(run_id, "claims", "running", progress=5)

    # Clear prior draft claims on re-run of Stage 1
    default_claim_repo.delete_claims_for_run(run_id)

    # 1. Target document extraction & Section 16.3 scoping
    default_broker.emit_activity(
        run_id=run_id,
        stage="claims",
        title="Extracting target PBRER structure",
        detail=f"Parsing {run['target_object_id']} and isolating Section 16.3",
        kind="tool",
        agent="DocumentUnderstanding",
    )
    doc_data = build_full_document_model(run["target_object_id"], run_id)
    default_broker.emit_stage_update(run_id, "claims", "running", progress=15)

    # 2. Phase 1A — Per-file source exploration via Agentic Harness -> Master Summary .md
    explore_res = explore_all_sources_with_harness(
        run_id=run_id,
        source_paths=run["source_object_ids"],
    )
    default_broker.emit_stage_update(run_id, "claims", "running", progress=55)

    # 3. Phase 1B — Subsection-by-subsection claims via Strands Agent + @tool
    claims = extract_claims_by_subsection(
        run_id=run_id,
        doc_data=doc_data,
        master_summary_md=explore_res["master_summary_md"],
        per_file_mds=explore_res["per_file_mds"],
        file_profiles=explore_res["file_profiles"],
    )
    default_broker.emit_stage_update(run_id, "claims", "running", progress=90)

    # 4. Freeze Stage 1 claims register & compute Stage 1 manifest hash
    claims_json = json.dumps(claims, indent=2)
    reg_storage = default_storage.put_derived(
        tenant_id="default",
        run_id=run_id,
        logical_path="stage_1_claims/claims_register.v001.json",
        body=claims_json,
    )
    reg_id = f"art_{hashlib.md5(f'{run_id}:stage_1_claims/claims_register.v001.json:claims'.encode()).hexdigest()[:12]}"
    reg_artifact = {
        "artifact_id": reg_id,
        "run_id": run_id,
        "stage": "claims",
        "claim_id": None,
        "logical_path": "stage_1_claims/claims_register.v001.json",
        "version": 1,
        "sha256": reg_storage["sha256"],
        "media_type": "application/json",
        "size_bytes": reg_storage["size_bytes"],
        "producer_agent_id": "Stage1Orchestrator",
        "status": "review",
    }
    default_artifact_repo.add_artifact(reg_artifact)
    default_broker.emit_artifact_ready(run_id, "claims", reg_artifact)

    stage1_manifest_hash = hashlib.sha256(
        f"{expected_input_manifest_hash}:{reg_storage['sha256']}".encode()
    ).hexdigest()
    default_run_repo.set_manifest_hash(run_id, "claims", stage1_manifest_hash)

    latest = default_run_repo.get_run(run_id)
    default_run_repo.transition(
        run_id=run_id,
        expected_version=latest["version"],
        new_state=RunState.CLAIMS_AWAITING_REVIEW,
        active_stage=None,
    )

    default_broker.emit_stage_update(run_id, "claims", "review", progress=100)
    default_broker.emit_activity(
        run_id=run_id,
        stage="claims",
        title="Stage 1 ready for review",
        detail=f"{len(claims)} hierarchical claim group(s) extracted · master_source_summary.md ready",
        kind="gate",
        status="warning",
    )
    default_broker.emit_run_finished(run_id, "claims", {"claim_count": len(claims)})

    return {
        "run_id": run_id,
        "status": RunState.CLAIMS_AWAITING_REVIEW.value,
        "stage_1_manifest_hash": stage1_manifest_hash,
        "claim_count": len(claims),
    }

