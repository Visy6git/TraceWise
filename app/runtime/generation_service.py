"""Future-year generator service; consumes approved blueprint + new source files only."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.runtime.execution_boundary import get_generation_executor
from app.runtime.source_compatibility import profile_source_headers, compare_to_blueprint
from app.services.blueprint_repository import default_blueprint_repo
from app.services.event_stream import default_broker
from app.services.storage import default_storage


class SecurityError(RuntimeError):
    """Raised when an output artifact or operation violates a security boundary."""


def load_blueprint_package(
    tenant_id: str,
    blueprint_id: str,
    version: int,
    *,
    require_approved: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    record = default_blueprint_repo.get(tenant_id, blueprint_id, version)
    if not record:
        raise ValueError(f"Blueprint {blueprint_id} version {version} not found")
    if require_approved and record.get("version_status") != "approved":
        raise ValueError("Only an explicitly approved blueprint version can be used for generation")
    manifest = record.get("manifest") or {}
    prefix = f"blueprints-{tenant_id}/{blueprint_id}/versions/v{version:03d}"
    files = {
        item.get("path"): item
        for item in manifest.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    required = ("blueprint.json", "reproduce_section.py")
    missing = [path for path in required if path not in files]
    if missing:
        raise ValueError(
            "Blueprint package is incomplete; missing required runtime file(s): "
            f"{', '.join(missing)}. Create and approve a complete Stage 3 blueprint before generation."
        )
    if not require_approved and record.get("version_status") not in {"ready_for_review", "approved"}:
        raise ValueError(
            "Blueprint candidate has not passed Stage 3 structural validation and cannot be approved"
        )

    try:
        blueprint_bytes = default_storage.read_bytes(f"{prefix}/blueprint.json")
        script_bytes = default_storage.read_bytes(f"{prefix}/reproduce_section.py")
    except FileNotFoundError as exc:
        raise ValueError(
            "Blueprint package manifest references a missing runtime file. Create and approve "
            "a complete Stage 3 blueprint before generation."
        ) from exc

    bp_obj = files["blueprint.json"]
    script_obj = files["reproduce_section.py"]
    for path, content in (
        ("blueprint.json", blueprint_bytes),
        ("reproduce_section.py", script_bytes),
    ):
        expected_hash = files[path].get("sha256")
        if expected_hash and hashlib.sha256(content).hexdigest() != expected_hash:
            raise ValueError(f"Blueprint package integrity check failed for {path}")
    if not script_bytes.strip():
        raise ValueError("Blueprint package contains an empty reproduce_section.py")

    blueprint = json.loads(blueprint_bytes)
    validation = blueprint.get("validation") or {}
    if blueprint.get("status") not in {"ready_for_review", "approved"} or validation.get("status") == "blocked":
        raise ValueError(
            "Blueprint failed Stage 3 structural validation and cannot be approved or used "
            "for generation. Create and approve a complete blueprint candidate."
        )
    return blueprint, {
        "manifest": manifest,
        "prefix": prefix,
        "blueprint_obj": bp_obj,
        "script_obj": script_obj,
    }


def _validate_output_file(path: Path, name: str, workspace: Path) -> bytes:
    """Validate that the generated output artifact is safe, within workspace and well-formed."""
    resolved_ws = workspace.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_ws)
    except ValueError as exc:
        raise SecurityError(f"Output file {name} escaped the workspace directory boundary") from exc

    if not resolved_path.is_file():
        raise RuntimeError(f"Required generation output missing or not a regular file: {name}")

    content = resolved_path.read_bytes()
    if len(content) == 0:
        raise RuntimeError(f"Generation output {name} is empty (0 bytes)")

    if name.endswith(".docx"):
        # DOCX must be a valid zip archive (starts with PK\x03\x04 or PK\x05\x06)
        if not content.startswith(b"PK\x03\x04") and not content.startswith(b"PK\x05\x06"):
            raise ValueError(f"Generated {name} is not a valid DOCX/OpenXML document")
    elif name.endswith(".json"):
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Generated {name} contains malformed JSON") from exc

    return content


def run_generation(generation_id: str) -> dict[str, Any]:
    record = default_blueprint_repo.get_generation(generation_id)
    if not record:
        raise ValueError(f"Generation run {generation_id} not found")
    tenant_id = record["tenant_id"]
    blueprint, pkg = load_blueprint_package(
        tenant_id, record["blueprint_id"], record["blueprint_version"]
    )
    run_dir = default_storage.run_dir(generation_id)
    source_dir = run_dir / "input" / "sources"
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    default_blueprint_repo.update_generation(generation_id, tenant_id=tenant_id, status="profiling")
    default_broker.emit_run_started(generation_id, "generation")
    default_broker.emit_stage_update(generation_id, "generation", "profiling", progress=8)

    profiles = profile_source_headers(source_dir)
    compatibility = compare_to_blueprint(
        generation_id=generation_id,
        blueprint=blueprint,
        source_manifest_hash=record["source_manifest_hash"],
        profiles=profiles,
    )
    compatibility_path = workspace / "compatibility_report.json"
    compatibility_path.write_text(compatibility.model_dump_json(indent=2), encoding="utf-8")
    proposal = None
    if compatibility.status != "compatible":
        # Harness is used as a bounded schema-drift coding assistant. It can write
        # a proposal and synthetic tests, but cannot edit or approve the blueprint.
        from app.runtime.schema_drift_assistant import propose_schema_drift
        proposal_dir = workspace / "schema_drift_proposal"
        try:
            proposal = propose_schema_drift(
                generation_id=generation_id,
                blueprint=blueprint,
                profiles=profiles,
                compatibility_report=compatibility.model_dump(mode="json"),
                workspace_dir=proposal_dir,
            )
        except Exception as exc:
            proposal = {"status": "assistant_unavailable", "reason": str(exc), "requires_reviewer_approval": True}
        (workspace / "proposed_mappings.json").write_text(json.dumps(proposal, indent=2), encoding="utf-8")

    default_blueprint_repo.update_generation(
        generation_id,
        tenant_id=tenant_id,
        compatibility_json={**compatibility.model_dump(mode="json"), "mapping_proposal": proposal},
        status="compatibility_review" if compatibility.status != "compatible" else "ready",
    )
    default_broker.emit_activity(
        generation_id,
        "generation",
        "Source compatibility checked",
        f"{compatibility.status}: {len(compatibility.drift)} schema drift finding(s). No calculation starts before blockers are resolved.",
        kind="gate",
        status="warning" if compatibility.status != "compatible" else "done",
    )

    if compatibility.status != "compatible":
        # Both warnings and blockers are review-gated. A changed field mapping is
        # not silently committed against an approved blueprint version.
        default_storage.put_derived(
            tenant_id=tenant_id,
            run_id=generation_id,
            logical_path="outputs/compatibility_report.json",
            body=json.dumps({**compatibility.model_dump(mode="json"), "mapping_proposal": proposal}, indent=2),
        )
        default_broker.emit_stage_update(generation_id, "generation", "compatibility_review", progress=100)
        default_broker.emit_run_finished(generation_id, "generation", {"status": "compatibility_review"})
        return {
            "generation_id": generation_id,
            "status": "compatibility_review",
            "compatibility": compatibility.model_dump(mode="json"),
            "mapping_proposal": proposal,
        }

    # Copy only the approved runtime package files into the generation workspace.
    # No learning-run input or target PBRER is needed or made visible to this runtime.
    blueprint_path = workspace / "blueprint.json"
    script_path = workspace / "reproduce_section.py"
    blueprint_path.write_text(json.dumps(blueprint, indent=2), encoding="utf-8")
    script_path.write_bytes(default_storage.read_bytes(f"{pkg['prefix']}/reproduce_section.py"))
    context_path = workspace / "generation_context.json"
    context_path.write_text(json.dumps({
        "generation_id": generation_id,
        "tenant_id": tenant_id,
        "blueprint_id": record["blueprint_id"],
        "blueprint_version": record["blueprint_version"],
        "reporting_period_start": record["reporting_period_start"],
        "reporting_period_end": record["reporting_period_end"],
        "as_of_date": record.get("as_of_date"),
        "source_manifest_hash": record["source_manifest_hash"],
        "source_profiles": profiles,
        "approved_field_mappings": compatibility.mappings,
    }, indent=2), encoding="utf-8")

    default_blueprint_repo.update_generation(generation_id, tenant_id=tenant_id, status="running")
    default_broker.emit_stage_update(generation_id, "generation", "running", progress=30)

    executor = get_generation_executor()
    result = executor.execute(
        generation_id=generation_id,
        script_path="reproduce_section.py",
        workspace_dir=workspace,
        source_input_dir=source_dir,
        generation_context_path=context_path,
    )
    if result.get("exit_code") != 0 or result.get("status") != "success":
        raise RuntimeError(f"Generation executor failed: {result.get('stderr') or result}")

    output_names = ["section_16_3.docx", "result.json", "lineage.json", "exceptions.json"]
    artifacts = []
    manifest_items = []
    for name in output_names:
        path = workspace / name
        content = _validate_output_file(path, name, workspace)
        stored = default_storage.put_derived(
            tenant_id=tenant_id,
            run_id=generation_id,
            logical_path=f"outputs/{name}",
            body=content,
        )
        entry = {
            "artifact_id": "genart_" + hashlib.sha256(f"{generation_id}:{name}:{stored['sha256']}".encode()).hexdigest()[:16],
            "generation_id": generation_id,
            "logical_path": f"outputs/{name}",
            "media_type": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if name.endswith(".docx")
                else "application/json"
            ),
            "sha256": stored["sha256"],
            "size_bytes": stored["size_bytes"],
            "status": "ready",
        }
        artifacts.append(entry)
        manifest_items.append({"path": name, "sha256": stored["sha256"], "size_bytes": stored["size_bytes"]})
        default_broker.emit_artifact_ready(generation_id, "generation", {**entry, "stage": "generation"})

    output_hash = hashlib.sha256(json.dumps(manifest_items, sort_keys=True).encode()).hexdigest()
    default_blueprint_repo.update_generation(
        generation_id,
        tenant_id=tenant_id,
        status="output_review",
        output_manifest_hash=output_hash,
        artifacts_json=artifacts,
    )
    default_broker.emit_stage_update(generation_id, "generation", "output_review", progress=100)
    default_broker.emit_run_finished(
        generation_id,
        "generation",
        {"status": "output_review", "output_manifest_hash": output_hash},
    )
    return {
        "generation_id": generation_id,
        "status": "output_review",
        "output_manifest_hash": output_hash,
        "artifacts": artifacts,
    }
