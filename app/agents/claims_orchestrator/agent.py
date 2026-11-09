"""Stage 1: Claims Orchestrator implementation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.agents.base import AgentRuntimeConfig, build_strands_agent
from app.agents.claims_orchestrator.claim_atomizer import atomize_document_claims
from app.agents.claims_orchestrator.document_understanding import build_full_document_model
from app.agents.claims_orchestrator.source_survey import survey_all_sources
from app.control_plane.run_state import RunState
from app.services.database import default_claim_repo, default_run_repo
from app.services.event_stream import default_broker
from app.services.storage import default_storage
from app.tools.artifact_tools import publish_artifact


def create_claims_agent(model_id: str, tools: list[Any], workspace_id: str) -> Any:
    cfg = AgentRuntimeConfig(
        agent_id="claims-orchestrator",
        stage="claims",
        model_id=model_id,
        system_prompt=(
            "Read the entire target report and all source metadata. Build leaf-level atomic claims "
            "and one concise evidence hint per claim. Do not calculate final values."
        ),
        tool_profile="claims_read_all_inputs_claim_registry_write",
        max_turns=40,
        workspace_id=workspace_id,
    )
    return build_strands_agent(cfg, tools)


def run_claims_stage(run_id: str, frozen_input_manifest: str | None = None) -> dict[str, Any]:
    """Execute complete Stage 1: Document Understanding, Source Survey, and Claim Atomization."""
    run = default_run_repo.get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    default_broker.emit_stage_update(run_id, "claims", "running", progress=10)
    default_broker.emit_activity(
        run_id=run_id,
        stage="claims",
        title="Claims Orchestrator started",
        detail="Beginning document understanding and source survey.",
        kind="agent",
        agent="claims-orchestrator",
    )

    # Ensure in CLAIMS_RUNNING state
    cur = default_run_repo.get_run(run_id)
    if cur["status"] == RunState.READY_FOR_STAGE_1.value:
        cur = default_run_repo.transition(
            run_id=run_id,
            expected_version=cur["version"],
            new_state=RunState.CLAIMS_RUNNING,
            active_stage="claims",
        )

    # 1. Locate target document
    target_obj_id = run.get("target_object_id")
    target_path = None
    if target_obj_id and Path(target_obj_id).exists():
        target_path = Path(target_obj_id).resolve()
    else:
        # Check in storage or sample fallback
        cand = default_storage.root_dir / "default" / run_id / "input" / "target"
        if cand.exists():
            files = list(cand.glob("*.docx"))
            if files:
                target_path = files[0]
        if not target_path:
            sample_docx = Path("runtime/sample_pbrer_data/PBRER_Annual_Report_2024_Nexipril.docx").resolve()
            if sample_docx.exists():
                target_path = sample_docx

    if not target_path or not target_path.exists():
        raise FileNotFoundError(f"Target document not found for run {run_id}")

    default_broker.emit_activity(
        run_id=run_id,
        stage="claims",
        title="Extracting target document",
        detail=f"Parsing {target_path.name} structure and locators",
        kind="tool",
        source=target_path.name,
    )

    doc_data = build_full_document_model(target_path, run_id)

    # 2. Locate source files
    source_obj_ids = run.get("source_object_ids", [])
    source_files: list[Path] = []
    for s in source_obj_ids:
        sp = Path(s)
        if sp.exists():
            source_files.append(sp.resolve())

    if not source_files:
        # Check storage input sources or sample fallback
        src_cand = default_storage.root_dir / "default" / run_id / "input" / "sources"
        if src_cand.exists():
            source_files = list(src_cand.glob("*.xlsx")) + list(src_cand.glob("*.csv"))
        if not source_files:
            sample_dir = Path("runtime/sample_pbrer_data").resolve()
            if sample_dir.exists():
                source_files = [p for p in sample_dir.glob("*.xlsx")]

    default_broker.emit_stage_update(run_id, "claims", "running", progress=35)
    default_broker.emit_activity(
        run_id=run_id,
        stage="claims",
        title="Surveying sources",
        detail=f"Profiling {len(source_files)} uploaded source workbooks",
        kind="tool",
    )

    source_knowledge = survey_all_sources(run_id, source_files)

    # 3. Atomize claims from document blocks
    default_broker.emit_stage_update(run_id, "claims", "running", progress=60)
    default_broker.emit_activity(
        run_id=run_id,
        stage="claims",
        title="Atomizing claims",
        detail="Extracting atomic claims and evidence hints for Section 16.3 / leaf sections",
        kind="agent",
        agent="claims-orchestrator",
    )

    claims = atomize_document_claims(doc_data["blocks"], source_knowledge)

    # 4. Save into Claim Registry
    saved_claims = []
    for c in claims:
        saved = default_claim_repo.save_claim(run_id, c.model_dump())
        saved_claims.append(saved)
        default_broker.emit_claim_update(run_id, c.claim_id, c.section_id, c.status.value)

    # 5. Publish Stage 1 Artifacts
    claims_register_json = json.dumps([c.model_dump() for c in claims], indent=2)
    default_storage.put_immutable(
        tenant_id="default",
        run_id=run_id,
        logical_path="stage_1_claims/claims_register.v001.json",
        body=claims_register_json,
    )

    artifacts_to_publish = [
        ("stage_1_claims/source_knowledge.md", "text/markdown"),
        ("stage_1_claims/source_knowledge.json", "application/json"),
        ("stage_1_claims/knowledge_graph.json", "application/json"),
        ("stage_1_claims/schema_profiles.json", "application/json"),
        ("stage_1_claims/relationships.json", "application/json"),
        ("stage_1_claims/claims_register.v001.json", "application/json"),
    ]

    manifest_entries = []
    hasher = hashlib.sha256()
    for rel_path, media_type in artifacts_to_publish:
        content = default_storage.read_text(f"default/{run_id}/{rel_path}")
        hasher.update(content.encode("utf-8"))
        entry = publish_artifact(
            run_id=run_id,
            stage="claims",
            claim_id=None,
            logical_path=rel_path,
            media_type=media_type,
            content=content,
            producer_agent_id="claims-orchestrator",
        )
        manifest_entries.append(entry)
        default_broker.emit_artifact_update(
            run_id=run_id,
            artifact_id=entry["artifact_id"],
            logical_path=entry["logical_path"],
            version=entry["version"],
            sha256=entry["sha256"],
        )

    stage_1_manifest_hash = hasher.hexdigest()
    default_run_repo.set_manifest_hash(run_id, "claims", stage_1_manifest_hash)

    # 6. Transition state to CLAIMS_AWAITING_REVIEW
    current_run = default_run_repo.get_run(run_id)
    updated_run = default_run_repo.transition(
        run_id=run_id,
        expected_version=current_run["version"],
        new_state=RunState.CLAIMS_AWAITING_REVIEW,
        active_stage=None,
    )

    default_broker.emit_stage_update(run_id, "claims", "review", progress=100)
    default_broker.emit_activity(
        run_id=run_id,
        stage="claims",
        title="Stage 1 complete: Awaiting Review",
        detail=f"Extracted {len(saved_claims)} claims. Manifest hash: {stage_1_manifest_hash[:12]}...",
        kind="gate",
        status="done",
    )

    return {
        "status": "CLAIMS_AWAITING_REVIEW",
        "stage_1_manifest_hash": stage_1_manifest_hash,
        "total_claims": len(saved_claims),
        "claims": saved_claims,
    }
