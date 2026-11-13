"""Stage 3 orchestrator: build a reusable Section 16.3 reproduction blueprint.

Execution note: it deliberately reuses app.harness.runner.run_harness_task. The
current harness ShellTool executes commands on the worker host, so this adapter
is development-only until the harness shell is routed to an isolated worker.
Production must refuse to start unless TRACEWISE_HARNESS_EXECUTION=isolated.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.control_plane.run_state import RunState
from app.harness.runner import HarnessRunResult, run_harness_task
from app.services.database import default_artifact_repo, default_run_repo
from app.services.event_stream import default_broker
from app.services.storage import default_storage
from app.stages.stage_3_understanding.artifact_builder import (
    build_bootstrap_blueprint, build_input_inventory, validate_blueprint_package,
)
from app.stages.stage_3_understanding.prompts import STAGE_3_SYSTEM_PROMPT
from app.schemas.blueprint import SectionReproductionBlueprint

_STAGE3_REPAIR_ATTEMPTS = 2


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _publish_learning_artifact(run_id: str, logical_path: str, path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    stored = default_storage.put_derived(
        tenant_id="default", run_id=run_id, logical_path=logical_path, body=content,
    )
    artifact_id = "art_" + hashlib.sha256(f"{run_id}:{logical_path}:{stored['sha256']}".encode()).hexdigest()[:16]
    entry = {
        "artifact_id": artifact_id, "run_id": run_id, "stage": "evaluation",
        "claim_id": None, "logical_path": logical_path, "version": 1,
        "sha256": stored["sha256"], "media_type": _media_type(path),
        "size_bytes": stored["size_bytes"], "producer_agent_id": "Stage3UnderstandingHarness",
        "status": "review",
    }
    default_artifact_repo.add_artifact(entry)
    default_broker.emit_artifact_ready(run_id, "understanding", entry)
    return entry


def _media_type(path: Path) -> str:
    return {
        ".json": "application/json", ".md": "text/markdown", ".py": "text/x-python",
        ".txt": "text/plain", ".yaml": "application/yaml",
    }.get(path.suffix.lower(), "application/octet-stream")


def _run_harness_with_package_repairs(
    *,
    run_id: str,
    blueprint_id: str,
    workspace: Path,
    readonly_inputs: Path,
    env_vars: dict[str, str],
    goal: str,
) -> tuple[HarnessRunResult, dict[str, Any], list[dict[str, Any]]]:
    """Continue the authoring agent when validation finds required files missing."""
    attempts: list[HarnessRunResult] = []
    validation = validate_blueprint_package(workspace)

    for attempt_number in range(_STAGE3_REPAIR_ATTEMPTS + 1):
        if attempt_number == 0:
            attempt_goal = goal
            max_turns = 40
        else:
            missing = validation["missing_files"]
            if not missing:
                break
            default_broker.emit_activity(
                run_id,
                "understanding",
                "Continuing Stage 3 package authoring",
                f"Validation found {len(missing)} required file(s) missing; requesting a bounded repair pass.",
                kind="system",
                agent="Section16_3UnderstandingOrchestrator",
                status="warning",
            )
            attempt_goal = f"""Continue the existing Stage 3 authoring attempt for learning run {run_id} and blueprint {blueprint_id}.

The previous harness response ended before these required workspace files were created:
{chr(10).join(f"- {name}" for name in missing)}

Create these files now in the existing writable workspace. Do not repeat broad input exploration or recreate files that already exist. Read only the smallest relevant existing workspace/read-only artifacts needed to ground each output. Preserve observed, inferred, and unknown distinctions. If evidence is insufficient, document the unknown and make reproduce_section.py fail closed for that mapping rather than inventing behavior.

Do not run reproduction tests with the local harness shell. Do not claim test success or create reproduction_test_report.json; only an approved isolated executor can produce that evidence. Do not create or modify blueprint_validation.json; the orchestrator writes that report. Finish the missing files, update blueprint.json with grounded blockers, and stop."""
            max_turns = 16

        result = run_harness_task(
            run_id=run_id,
            stage="understanding",
            agent_id=(
                "Section16_3UnderstandingHarness"
                if attempt_number == 0
                else f"Section16_3UnderstandingRepair{attempt_number}"
            ),
            goal=attempt_goal,
            workspace_dir=workspace,
            readonly_dirs=[readonly_inputs],
            env_vars=env_vars,
            developer_instructions=STAGE_3_SYSTEM_PROMPT,
            max_turns=max_turns,
            emit_events=True,
        )
        attempts.append(result)
        validation = validate_blueprint_package(workspace)

    last_result = attempts[-1] if attempts else HarnessRunResult(
        success=True,
        final_response="",
        turns=0,
        tool_calls_count=0,
    )
    attempt_summaries = [
        {
            "attempt": index + 1,
            "success": result.success,
            "turns": result.turns,
            "tool_calls": result.tool_calls_count,
            "error": result.error,
        }
        for index, result in enumerate(attempts)
    ]
    return last_result, validation, attempt_summaries


def _copy_package_to_blueprint_library(tenant_id: str, blueprint_id: str, version: int, workspace: Path) -> dict[str, Any]:
    """Publish package files into private, immutable blueprint storage.

    Uses StorageService immutable-object semantics. Blueprint versions are globally
    addressable by (tenant, blueprint_id, version), not nested inside a source run.
    """
    file_manifest = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(workspace).as_posix()
        if relative == "blueprint_manifest.json":
            continue
        logical = f"versions/v{version:03d}/{relative}"
        stored = default_storage.put_immutable(
            tenant_id=f"blueprints-{tenant_id}", run_id=blueprint_id,
            logical_path=logical, body=path.read_bytes(),
        )
        file_manifest.append({
            "path": relative, "object_id": stored["object_id"],
            "sha256": stored["sha256"], "size_bytes": stored["size_bytes"],
            "media_type": _media_type(path),
        })
    manifest = {
        "schema_version": "1.0", "blueprint_id": blueprint_id, "version": version,
        "tenant_id": tenant_id, "files": file_manifest,
        "manifest_hash": hashlib.sha256(json.dumps(file_manifest, sort_keys=True).encode()).hexdigest(),
    }
    manifest_path = workspace / "blueprint_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    stored = default_storage.put_immutable(
        tenant_id=f"blueprints-{tenant_id}", run_id=blueprint_id,
        logical_path=f"versions/v{version:03d}/blueprint_manifest.json",
        body=manifest_path.read_bytes(),
    )
    manifest["manifest_object_id"] = stored["object_id"]
    return manifest


def run_understanding_stage(run_id: str, expected_stage_2_manifest_hash: str) -> dict[str, Any]:
    """Run Stage 3 against the frozen/approved Stage 1 and Stage 2 outputs.

    The control plane/API must have transitioned the run to EVALUATION_RUNNING
    before calling this function. Existing persisted `evaluation` naming is kept
    as a compatibility key; UI copy and artifacts use `understanding`.
    """
    run = default_run_repo.get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")
    if run.get("stage_2_manifest_hash") != expected_stage_2_manifest_hash:
        raise ValueError("Stage 2 manifest mismatch: current approved Rules output changed")
    if RunState(run["status"]) != RunState.EVALUATION_RUNNING:
        raise ValueError("Stage 3 can execute only after the control plane enters EVALUATION_RUNNING")

    environment = os.environ.get("TRACEWISE_ENV", "development").lower()
    execution_mode = os.environ.get("TRACEWISE_HARNESS_EXECUTION", "development").lower()
    if environment == "production":
        # Setting an environment flag alone cannot turn the existing ShellTool
        # into an isolated executor. A real remote harness worker must be wired
        # before this production entry point is enabled.
        raise RuntimeError(
            "Stage 3 blocked: the current Harness ShellTool executes host subprocesses. "
            "Integrate an isolated harness worker adapter; do not bypass this guard with an env flag."
        )
    if execution_mode != "development":
        raise RuntimeError("Unsupported Stage 3 authoring execution mode; use the development harness only locally")

    default_broker.emit_run_started(run_id, "understanding")
    default_broker.emit_stage_update(run_id, "understanding", "running", progress=3)
    default_broker.emit_activity(
        run_id, "understanding", "Creating reproduction blueprint workspace",
        "Inspecting only approved Stage 1/2 artifacts; upstream sources and claims remain unchanged.",
        kind="agent", agent="Section16_3UnderstandingOrchestrator", status="running",
    )

    run_dir = default_storage.run_dir(run_id)
    stage1_dir = run_dir / "stage_1_claims"
    stage2_dir = run_dir / "stage_2_rules"
    if not stage1_dir.exists() or not stage2_dir.exists():
        raise FileNotFoundError("Approved Stage 1 and Stage 2 artifact directories are required")

    blueprint_id = f"bp_{uuid.uuid4().hex[:16]}"
    version = 1
    attempt_id = uuid.uuid4().hex[:12]
    attempt_root = run_dir / "stage_3_understanding" / "attempts" / attempt_id
    workspace = attempt_root / "workspace"
    readonly_inputs = attempt_root / "read_only_inputs"
    workspace.mkdir(parents=True, exist_ok=False)
    from app.stages.stage_3_understanding.artifact_builder import prepare_stage3_readonly_inputs
    inventory = prepare_stage3_readonly_inputs(run_dir, readonly_inputs)
    safe_stage1 = readonly_inputs / "stage_1_claims"
    safe_stage2 = readonly_inputs / "stage_2_rules"
    bootstrap = build_bootstrap_blueprint(
        run_id=run_id, run=run, stage1_dir=safe_stage1, stage2_dir=safe_stage2,
        blueprint_id=blueprint_id, version=version,
    )
    (workspace / "blueprint.json").write_text(json.dumps(bootstrap, indent=2), encoding="utf-8")
    (workspace / "input_inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")

    goal = f"""Build an approved-methodology candidate for Section 16.3 using the existing files in your workspace and read-only inputs.

Learning run: {run_id}
Blueprint ID: {blueprint_id}
Blueprint version: {version}
Approved Stage 1 manifest: {run.get('stage_1_manifest_hash')}
Approved Stage 2 manifest: {expected_stage_2_manifest_hash}

Read input_inventory.json first. Read the sanitized Stage 1/2 artifacts from the configured read-only directory. Row-level evidence payloads, raw source files and tool transcripts have intentionally been excluded. Use aggregate results, rule specs, provenance and source schema profiles. The pre-created blueprint.json is a conservative bootstrap, not a finished blueprint. Complete every required output file in your workspace as specified by your system prompt. Never modify read-only directories. Preserve observed/inferred/unknown. Write reproduce_section.py and tests; if a mapping is unknown, make the runtime fail closed for it. Do not claim tests passed unless executed through a separately isolated execution backend. Do not create blueprint_validation.json; the orchestrator writes it. Agent must not set status=approved.
"""

    default_broker.emit_stage_update(run_id, "understanding", "running", progress=12, attempt_id=attempt_id)
    harness, validation, harness_attempts = _run_harness_with_package_repairs(
        run_id=run_id,
        blueprint_id=blueprint_id,
        workspace=workspace,
        readonly_inputs=readonly_inputs,
        env_vars={"TRACEWISE_STAGE": "understanding", "TRACEWISE_BLUEPRINT_ID": blueprint_id},
        goal=goal,
    )

    (workspace / "blueprint_validation.json").write_text(json.dumps({
        **validation,
        "harness_success": harness.success,
        "harness_turns": sum(item["turns"] for item in harness_attempts),
        "harness_tool_calls": sum(item["tool_calls"] for item in harness_attempts),
        "harness_error": harness.error,
        "harness_attempts": harness_attempts,
        "input_manifest_hashes": {
            "stage_1": run.get("stage_1_manifest_hash"),
            "stage_2": expected_stage_2_manifest_hash,
        },
    }, indent=2), encoding="utf-8")

    # Normalize generated blueprint metadata using the strict Pydantic contract.
    bp_path = workspace / "blueprint.json"
    if not bp_path.exists():
        raise RuntimeError("Harness did not produce blueprint.json")
    bp_data = json.loads(bp_path.read_text(encoding="utf-8"))
    bp_data["blueprint_id"] = blueprint_id
    bp_data["version"] = version
    bp_data["source_learning_run_id"] = run_id
    bp_data["source_stage_1_manifest_hash"] = run.get("stage_1_manifest_hash") or ""
    bp_data["source_stage_2_manifest_hash"] = expected_stage_2_manifest_hash
    bp_data["status"] = "needs_review" if validation["status"] == "blocked" or not harness.success else "ready_for_review"
    bp_data["created_by"] = "Section16_3UnderstandingOrchestrator"
    bp_data["validation"] = bp_data.get("validation") or {}
    bp_data["validation"]["status"] = validation["status"]
    bp_data["validation"]["unresolved_items"] = list(set(
        (bp_data["validation"].get("unresolved_items") or []) + validation["issues"] + validation["missing_files"]
    ))
    SectionReproductionBlueprint.model_validate(bp_data)
    bp_path.write_text(json.dumps(bp_data, indent=2), encoding="utf-8")

    # Publish run artifacts for immediate UI review. The versioned blueprint
    # library copy is separate and remains DRAFT/NEEDS_REVIEW until human approval.
    package_entries = []
    for path in sorted(workspace.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            rel = path.relative_to(workspace).as_posix()
            if rel == "blueprint_manifest.json":
                continue
            package_entries.append(_publish_learning_artifact(
                run_id, f"stage_3_understanding/blueprint_candidate/{rel}", path,
            ))
    lib_manifest = _copy_package_to_blueprint_library(run.get("tenant_id", "default"), blueprint_id, version, workspace)
    default_broker.emit_activity(
        run_id, "understanding", "Blueprint candidate packaged",
        f"{len(package_entries)} artifacts · harness {'completed' if harness.success else 'reported an error'} · validation {validation['status']}.",
        kind="artifact", agent="Section16_3UnderstandingOrchestrator", artifact="blueprint.json",
        status="warning" if validation["status"] == "blocked" else "done",
    )

    manifest_hash = lib_manifest["manifest_hash"]
    default_run_repo.set_manifest_hash(run_id, "evaluation", manifest_hash)
    latest = default_run_repo.get_run(run_id)
    package_ready = harness.success and validation["status"] != "blocked"
    failure_detail = None
    if not package_ready:
        blockers = validation["missing_files"] + validation["issues"]
        failure_detail = harness.error or (
            "Stage 3 package validation is blocked: " + "; ".join(blockers)
        )
    default_run_repo.transition(
        run_id=run_id, expected_version=latest["version"],
        new_state=RunState.EVALUATION_AWAITING_REVIEW if package_ready else RunState.FAILED,
        active_stage=None if package_ready else "evaluation",
    )
    default_broker.emit_stage_update(
        run_id, "understanding", "review" if package_ready else "error",
        progress=100, attempt_id=attempt_id,
    )
    default_broker.emit_activity(
        run_id, "understanding", "Stage 3 blueprint candidate ready for reviewer",
        (
            "Reviewer must inspect unresolved methodology, source contracts, schema drift policy and reproduction tests. Approval is not automatic."
            if package_ready
            else failure_detail or "Stage 3 package validation failed."
        ),
        kind="gate" if package_ready else "warning",
        status="warning" if not package_ready else "done",
    )
    if package_ready:
        default_broker.emit_run_finished(run_id, "understanding", {
            "blueprint_id": blueprint_id, "blueprint_version": version,
            "blueprint_status": bp_data["status"], "manifest_hash": manifest_hash,
            "harness_success": harness.success, "validation_status": validation["status"],
        })
    else:
        default_broker.emit_run_error(run_id, "understanding", failure_detail or "Stage 3 failed")

    # BlueprintRepository is imported lazily to avoid coupling the stage to DB init.
    from app.services.blueprint_repository import default_blueprint_repo
    default_blueprint_repo.register_candidate(
        blueprint_id=blueprint_id, tenant_id=run.get("tenant_id", "default"),
        source_learning_run_id=run_id, version=version, status=bp_data["status"],
        manifest_hash=manifest_hash, manifest=lib_manifest,
    )
    return {
        "run_id": run_id, "stage": "understanding",
        "status": "awaiting_review" if package_ready else "failed",
        "blueprint_id": blueprint_id, "blueprint_version": version,
        "blueprint_status": bp_data["status"], "manifest_hash": manifest_hash,
        "harness_success": harness.success, "validation": validation,
        "error": failure_detail,
        "artifact_count": len(package_entries),
    }
