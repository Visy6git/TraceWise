"""Harness-assisted schema-drift analysis that proposes, never applies, changes.

It intentionally receives only blueprint contracts + header/type profiles. No
raw source rows are provided. Proposed field maps are separate artifacts and
must be reviewed; accepting a semantic change creates a new blueprint version.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.harness.runner import run_harness_task
from app.stages.stage_3_understanding.prompts import STAGE_3_SYSTEM_PROMPT

DRIFT_PROMPT = """
You are the TraceWise source-schema compatibility specialist. Inspect blueprint.json,
source_profiles.json and compatibility_report.json. Use only schema metadata.
Do not read or request raw source rows. Produce:
- proposed_mappings.json: dataset_id, logical_field, old_physical_field,
  proposed_physical_field, evidence, confidence, semantic_risk, reviewer_required.
- drift_assessment.md: exact changes, missing contracts, ambiguous dataset matches,
  key/grain/type/date/version concerns and recommended reviewer decisions.
- tests/test_proposed_mappings.py: synthetic tests for candidate mappings.
Never edit blueprint.json. Never mark a mapping accepted. Never run generation.
A filename/worksheet rename is not proof of semantic equivalence. Changed key,
case/event grain, effective-date/version semantics, population or filter meaning
is blocking and must require a new approved blueprint version.
""".strip()


def propose_schema_drift(
    *, generation_id: str, blueprint: dict[str, Any], profiles: list[dict[str, Any]],
    compatibility_report: dict[str, Any], workspace_dir: Path,
) -> dict[str, Any]:
    if os.environ.get("TRACEWISE_ENV", "development").lower() == "production":
        raise RuntimeError("Production schema-drift assistant requires an isolated Harness worker adapter")
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "blueprint.json").write_text(json.dumps(blueprint, indent=2), encoding="utf-8")
    (workspace_dir / "source_profiles.json").write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    (workspace_dir / "compatibility_report.json").write_text(json.dumps(compatibility_report, indent=2), encoding="utf-8")
    result = run_harness_task(
        run_id=generation_id, stage="generation", agent_id="SchemaDriftAssistant",
        goal=("Analyze schema drift and propose a reviewer-gated mapping proposal. "
              "Do not execute the reproduction script, do not edit the blueprint, "
              "and do not access files outside this workspace. Produce the required outputs."),
        workspace_dir=workspace_dir, readonly_dirs=[],
        developer_instructions=STAGE_3_SYSTEM_PROMPT + "\n\n" + DRIFT_PROMPT,
        env_vars={"TRACEWISE_STAGE": "schema_drift", "TRACEWISE_GENERATION_ID": generation_id},
        max_turns=16,
    )
    proposal_path = workspace_dir / "proposed_mappings.json"
    proposal = json.loads(proposal_path.read_text(encoding="utf-8")) if proposal_path.exists() else {
        "status": "not_produced", "reason": result.error or "Harness did not produce proposed_mappings.json"
    }
    proposal["harness_success"] = result.success
    proposal["tool_calls"] = result.tool_calls_count
    proposal["requires_reviewer_approval"] = True
    proposal["may_modify_approved_blueprint"] = False
    return proposal
