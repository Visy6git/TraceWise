"""Stage 3 artifact packaging and deterministic bootstrap.

The bootstrap is intentionally conservative. It creates a draft contract from
Stage 1/2 artifacts so the harness has a navigable index. It does NOT claim to
have learned missing business rationale or synthesize executable PV logic.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "unknown"



def _sanitize_sensitive_tree(value: Any, key: str = "") -> Any:
    """Strip row-level records, sample values, transcripts and PHI structures from Stage 3 inputs."""
    blocked = {
        "rows", "records", "sample_rows", "sample_values", "unique_values",
        "raw_rows", "matched_rows", "claim_data", "patient_data", "person_data",
        "case_data", "stdout", "stderr", "tool_history", "tool_history_path",
        "patients", "subjects", "cases", "patient_list", "raw_data", "data_rows",
        "tool_output", "tool_input", "tool_arguments", "raw_prompt",
        "system_prompt_snapshot", "full_records", "individual_cases",
    }
    if isinstance(value, dict):
        return {
            k: _sanitize_sensitive_tree(v, k)
            for k, v in value.items()
            if k.lower() not in blocked
        }
    if isinstance(value, list):
        return [_sanitize_sensitive_tree(v, key) for v in value]
    return value


def prepare_stage3_readonly_inputs(run_dir: Path, destination: Path) -> dict[str, Any]:
    """Build a least-privilege, row-redacted snapshot from the approved stage outputs.

    No original workbook/CSV, raw evidence rows, claim_data, stdout/stderr or tool
    argument transcript is exposed to the Stage 3 coding agent. The agent receives
    complete section structure, schema-level source knowledge, Stage 2 rules and
    aggregate results/provenance. Add carefully reviewed metadata types here rather
    than widening access to complete run directories.
    """
    if destination.exists():
        shutil.rmtree(destination)
    s1_out = destination / "stage_1_claims"
    s2_out = destination / "stage_2_rules"
    ext_out = destination / "extracted"
    s1_out.mkdir(parents=True, exist_ok=True)
    s2_out.mkdir(parents=True, exist_ok=True)
    ext_out.mkdir(parents=True, exist_ok=True)
    s1 = run_dir / "stage_1_claims"
    s2 = run_dir / "stage_2_rules"
    copied: list[str] = []

    # Claims register: retain report statements/locators, but remove any accidental
    # row-level payload from hint/evidence extensions.
    for path in sorted(s1.glob("claims_register.v*.json")):
        data = _read_json(path, [])
        target = s1_out / path.name
        target.write_text(json.dumps(_sanitize_sensitive_tree(data), indent=2), encoding="utf-8")
        copied.append(target.relative_to(destination).as_posix())
    for name in ("source_knowledge.json",):
        path = s1 / name
        if path.exists():
            data = _sanitize_sensitive_tree(_read_json(path, {}))
            target = s1_out / name
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
            copied.append(target.relative_to(destination).as_posix())

    # Keep the Section 16.3 outline and extracted report blocks. They are needed to
    # preserve hierarchy/table/narrative construction; source patient rows are not.
    for name in ("sections.json", "target_document_blocks.json"):
        path = run_dir / "extracted" / name
        if path.exists():
            target = ext_out / name
            target.write_text(json.dumps(_sanitize_sensitive_tree(_read_json(path, [])), indent=2), encoding="utf-8")
            copied.append(target.relative_to(destination).as_posix())

    # Produce a schema-only Markdown source knowledge index; do not reuse source .md
    # files that may contain unredacted unique values or example records.
    sk = _read_json(s1 / "source_knowledge.json", {})
    lines = ["# Stage 3 source knowledge (redacted schema-level view)", "",
             "This input is generated from approved Stage 1 profiling. Raw rows, sample values and unique patient/case values are intentionally excluded.", ""]
    for ds in sk.get("datasets", []) if isinstance(sk, dict) else []:
        lines.extend([f"## {ds.get('dataset_id', 'dataset')}",
                      f"- Source: {ds.get('source_filename', 'unknown')}",
                      f"- Sheet/table: {ds.get('sheet_or_table', 'unknown')}",
                      f"- Rows: {ds.get('row_count', 'unknown')}",
                      f"- Columns: {', '.join(ds.get('data_columns') or [])}",
                      f"- Candidate keys: {', '.join(ds.get('candidate_key_columns') or [])}", ""])
    (s1_out / "source_knowledge.md").write_text("\n".join(lines), encoding="utf-8")
    copied.append("stage_1_claims/source_knowledge.md")

    allowed_names = {"plan.md", "rule_spec.json", "result.json", "execution.json",
                     "provenance.json", "artifact_manifest.json", "analysis.py",
                     "requirements.lock", "test_analysis.py"}
    if s2.exists():
        for path in sorted(s2.rglob("*")):
            if not path.is_file() or path.name not in allowed_names:
                continue
            relative = path.relative_to(s2)
            target = s2_out / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() == ".json":
                target.write_text(json.dumps(_sanitize_sensitive_tree(_read_json(path, {})), indent=2), encoding="utf-8")
            else:
                target.write_bytes(path.read_bytes())
            copied.append(target.relative_to(destination).as_posix())

    inventory = {"schema_version": "1.0", "files": []}
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            inventory["files"].append({
                "path": path.relative_to(destination).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            })
    inventory["file_count"] = len(inventory["files"])
    inventory_path = destination / "stage3_input_manifest.json"
    inventory_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return inventory

def build_input_inventory(stage1_dir: Path, stage2_dir: Path) -> dict[str, Any]:
    """Index only Stage 1/2 published artifacts; hashes prove exactly what Stage 3 saw."""
    entries = []
    for stage, root in (("claims", stage1_dir), ("rules", stage2_dir)):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                entries.append({
                    "stage": stage,
                    "logical_path": path.relative_to(root.parent).as_posix(),
                    "relative_path": path.relative_to(root).as_posix(),
                    "sha256": digest,
                    "size_bytes": path.stat().st_size,
                })
    return {"schema_version": "1.0", "artifacts": entries, "artifact_count": len(entries)}


def build_bootstrap_blueprint(
    *, run_id: str, run: dict[str, Any], stage1_dir: Path, stage2_dir: Path,
    blueprint_id: str, version: int = 1,
) -> dict[str, Any]:
    """Create a schema-shaped draft; live harness must enrich and validate it.

    This does not decide latest-record rules, filter rationale, or logical source
    mappings if Stage 2 artifacts do not state them explicitly.
    """
    claims = _read_json(stage1_dir / "claims_register.v001.json", [])
    if not claims:
        # Backward-compatible discovery of the latest claims register.
        candidates = sorted(stage1_dir.glob("claims_register.v*.json"))
        if candidates:
            claims = _read_json(candidates[-1], [])
    raw_sections = _read_json(stage1_dir.parent / "extracted" / "sections.json", [])
    # Adapt the extractor's tree/section records into the blueprint's explicit block model.
    section_blocks = []
    def walk_section(node: dict[str, Any], order: int = 0, parent: str | None = None) -> int:
        number = str(node.get("number") or node.get("section_number") or "16.3")
        title = str(node.get("title") or node.get("heading") or "")
        section_blocks.append({
            "block_id": str(node.get("section_id") or node.get("id") or f"heading-{number}-{order}"),
            "section_number": number, "parent_section_number": parent, "order": order,
            "block_type": "heading", "title": title, "text_template": None,
            "table_spec": None, "claim_bindings": [],
            "source_locator": {k: node.get(k) for k in ("section_id", "number", "title", "level", "parent_id") if k in node},
        })
        next_order = order + 1
        for child in node.get("children", []) or []:
            next_order = walk_section(child, next_order, number)
        return next_order
    if isinstance(raw_sections, list):
        order = 0
        for node in raw_sections:
            if isinstance(node, dict):
                order = walk_section(node, order)
    source_knowledge = _read_json(stage1_dir / "source_knowledge.json", {})

    claim_items = []
    for item in claims if isinstance(claims, list) else []:
        locator = item.get("target_locator") or {}
        hint = item.get("evidence_hint") or {}
        claim_items.append({
            "claim_id": item.get("claim_id"),
            "section_number": item.get("section_number", "16.3"),
            "target_locator": locator,
            "raw_statement": item.get("raw_statement", ""),
            "purpose": "UNKNOWN — must be grounded by Stage 3 from document context",
            "entity_definition": item.get("entity_unit") or "UNKNOWN",
            "unit": item.get("unit") or "UNKNOWN",
            "numerator_logic": None,
            "denominator_logic": None,
            "retrieval_policy_id": None,
            "dataset_ids": [],
            "transformations": [],
            "dependencies": [],
            "render_binding": {"target_locator": locator},
            "methodology_rationale": None,
            "rationale_state": "unknown",
            "stage_1_claim_version": item.get("version"),
            "stage_2_artifact_refs": [],
            "open_questions": ["Stage 3 must trace this claim to approved Stage 2 rule/evidence artifacts."],
            "stage_1_evidence_hint": hint,
            "stage_2_status_is_not_proof": True,
        })

    dataset_items = []
    for ds in source_knowledge.get("datasets", []) if isinstance(source_knowledge, dict) else []:
        dataset_items.append({
            "dataset_id": ds.get("dataset_id"),
            "purpose": "UNKNOWN — derive from actual claim/evidence usage",
            "source_candidates": [ds.get("source_filename")] if ds.get("source_filename") else [],
            "sheet_candidates": [ds.get("sheet_or_table")] if ds.get("sheet_or_table") else [],
            "fields": [],
            "entity_key": ds.get("candidate_key_columns") or [],
            "expected_grain": None,
            "join_contracts": [],
            "source_version_policy": {},
            "limitations": ds.get("warnings") or [],
            "stage_1_profile": ds,
        })

    inventory = build_input_inventory(stage1_dir, stage2_dir)
    return {
        "schema_version": "1.0",
        "blueprint_id": blueprint_id,
        "version": version,
        "status": "draft",
        "product_scope": run.get("product_name"),
        "section_number": "16.3",
        "source_learning_run_id": run_id,
        "source_stage_1_manifest_hash": run.get("stage_1_manifest_hash") or "",
        "source_stage_2_manifest_hash": run.get("stage_2_manifest_hash") or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "Stage3UnderstandingOrchestrator",
        "section_structure": section_blocks,
        "claims": claim_items,
        "datasets": dataset_items,
        "retrieval_policies": [],
        "transformation_graph": {"nodes": [], "edges": [], "validation": "pending"},
        "narrative_templates": [],
        "render_spec": {"blocks": [], "formatting": {}, "validation": "pending"},
        "schema_drift_policy": {
            "default_action": "block_on_semantic_drift",
            "safe_changes": ["new unused columns", "renamed file when schema fingerprint is unchanged"],
            "review_required": ["missing required field", "changed entity key", "changed version/date semantics", "changed filter meaning", "changed join cardinality"],
            "never_auto_accept": ["new latest-record policy", "changed case/event/patient grain", "changed population semantics"],
        },
        "reproducibility_contract": {
            "entrypoint": "reproduce_section.py",
            "inputs": ["blueprint.json", "generation_context.json", "source directory"],
            "outputs": ["section_16_3.docx", "result.json", "lineage.json", "exceptions.json"],
            "requires_isolated_execution": True,
        },
        "validation": {
            "status": "blocked", "checks": [], "reproduction_tested": False,
            "executable_present": False,
            "unresolved_items": [
                "Harness must resolve every claim to Stage 2 rule/evidence.",
                "Source field mappings and latest-record semantics are not inferred by bootstrap.",
                "Executable reproduction script and isolated test evidence are not yet present.",
            ],
            "tested_against_run_id": run_id,
        },
        "assumptions": [],
        "open_questions": [],
        "artifact_refs": {"input_inventory": "input_inventory.json"},
        "input_inventory": inventory,
    }


def validate_blueprint_package(
    workspace: Path,
    *,
    isolated_reproduction_test_passed: bool = False,
) -> dict[str, Any]:
    """Check package structure; only trusted executor results can satisfy test evidence."""
    required = [
        "blueprint.json", "section_model.json", "claim_catalog.json",
        "source_contracts.json", "retrieval_policies.json", "transformation_graph.json",
        "narrative_templates.json", "render_spec.json", "schema_drift_policy.json",
        "reproduce_section.py", "tests/test_reproduction_contract.py", "README.md",
    ]
    missing = [name for name in required if not (workspace / name).is_file()]
    issues: list[str] = []
    for name in required:
        path = workspace / name
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append(f"{name} is not valid UTF-8 text.")
            continue
        if not content.strip():
            issues.append(f"{name} is empty.")
        elif path.suffix.lower() == ".json":
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                issues.append(f"{name} is not valid JSON: {exc.msg}.")
        elif path.suffix.lower() == ".py":
            try:
                ast.parse(content, filename=name)
            except SyntaxError as exc:
                issues.append(f"{name} has a syntax error: {exc.msg}.")

    blueprint_path = workspace / "blueprint.json"
    if blueprint_path.exists():
        model = _read_json(blueprint_path, {})
        if not model.get("claims"):
            issues.append("Blueprint contains no claims.")
        if not model.get("section_structure"):
            issues.append("Blueprint contains no section structure.")
        if not isolated_reproduction_test_passed:
            issues.append("No isolated reproduction test evidence is recorded.")
        if model.get("status") == "approved":
            issues.append("Agent must never set blueprint status to approved.")
    return {
        "status": "blocked" if missing or issues else "structurally_ready_for_reviewer",
        "missing_files": missing,
        "issues": issues,
        "human_approval_required": True,
    }
