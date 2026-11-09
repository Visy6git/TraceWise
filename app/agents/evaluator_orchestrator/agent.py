"""Stage 3: Evaluator Orchestrator independent quality gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.agents.base import AgentRuntimeConfig, build_strands_agent
from app.agents.evaluator_orchestrator.evaluator_tools import rerun_artifact_independently
from app.agents.evaluator_orchestrator.independent_checks import evaluate_claim_independently
from app.control_plane.run_state import RunState
from app.services.database import default_claim_repo, default_eval_repo, default_run_repo
from app.services.event_stream import default_broker
from app.services.storage import default_storage
from app.tools.artifact_tools import publish_artifact
from app.tools.workspace_tools import get_claim_workspace_dir


def create_evaluator_agent(model_id: str, tools: list[Any], workspace_id: str) -> Any:
    cfg = AgentRuntimeConfig(
        agent_id="evaluator-orchestrator",
        stage="evaluation",
        model_id=model_id,
        system_prompt=(
            "Independently inspect and rerun every claim artifact read-only. "
            "Verify semantics, filters, joins, evidence, provenance and integrity. "
            "A numeric mismatch is not automatically a code failure."
        ),
        tool_profile="evaluator_read_only_sources_and_published_artifacts_independent_sandbox",
        max_turns=40,
        workspace_id=workspace_id,
    )
    return build_strands_agent(cfg, tools)


def run_evaluation_stage(run_id: str, stage_1_manifest: str | None = None, stage_2_manifest: str | None = None) -> dict[str, Any]:
    """Execute Stage 3: independent rerun, deterministic checks, and final evaluation dossier."""
    run = default_run_repo.get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    default_broker.emit_stage_update(run_id, "evaluation", "running", progress=5)
    default_broker.emit_activity(
        run_id=run_id,
        stage="evaluation",
        title="Evaluator Orchestrator started",
        detail="Beginning independent rerun and multi-point audit verification.",
        kind="agent",
        agent="evaluator-orchestrator",
    )

    # Ensure in EVALUATION_RUNNING state
    cur = default_run_repo.get_run(run_id)
    if cur["status"] == RunState.RULES_APPROVED.value:
        cur = default_run_repo.transition(
            run_id=run_id,
            expected_version=cur["version"],
            new_state=RunState.EVALUATION_RUNNING,
            active_stage="evaluation",
        )

    claims = default_claim_repo.list_claims(run_id)
    total_claims = len(claims)

    results = []
    hasher = hashlib.sha256()
    processed_count = 0

    for claim in claims:
        claim_id = claim["claim_id"]
        processed_count += 1
        progress = int((processed_count / total_claims) * 90)
        default_broker.emit_stage_update(run_id, "evaluation", "running", progress=progress)

        default_broker.emit_activity(
            run_id=run_id,
            stage="evaluation",
            title=f"Evaluating {claim_id}",
            detail="Rerunning calculation in clean sandbox and checking 13 validation criteria",
            kind="tool",
        )

        ws_dir = get_claim_workspace_dir(claim_id, run_id=run_id)

        # Load published Stage 2 artifacts
        rule_bundle: dict[str, Any] = {}
        eb_path = ws_dir / "evidence_bundle.json"
        if eb_path.exists():
            try:
                rule_bundle["evidence_bundle"] = json.loads(eb_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Perform independent execution in a clean sandbox
        evaluator_run = rerun_artifact_independently(claim_id, run_id=run_id)

        # Perform independent multi-point checks
        eval_result = evaluate_claim_independently(claim, rule_bundle, evaluator_run)
        eval_dict = eval_result.model_dump()
        results.append(eval_dict)

        # Persist in DB and storage
        default_eval_repo.save_evaluation(run_id, claim_id, eval_dict)

        eval_json = json.dumps(eval_dict, indent=2)
        hasher.update(eval_json.encode("utf-8"))
        logical_path = f"stage_3_evaluation/claims/{claim_id}/evaluation.json"
        publish_artifact(
            run_id=run_id,
            stage="evaluation",
            claim_id=claim_id,
            logical_path=logical_path,
            media_type="application/json",
            content=eval_json,
            producer_agent_id="evaluator-orchestrator",
        )

        # Update claim status in registry based on evaluation outcome
        new_status = "pass" if eval_result.status.value == "PASS" else "discrepancy"
        default_claim_repo.update_claim_patch(
            run_id=run_id,
            claim_id=claim_id,
            expected_version=claim.get("version", 1),
            patch={"status": new_status},
            reviewer_reason=f"Stage 3 independent evaluation outcome: {eval_result.status.value}",
            actor_id="evaluator-orchestrator",
        )
        default_broker.emit_claim_update(run_id, claim_id, claim["section_id"], new_status)

    # Compile comprehensive evaluation report
    passed_count = sum(1 for r in results if r["status"] == "PASS")
    discrepancy_count = sum(1 for r in results if r["status"] == "DISCREPANCY")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")

    evaluation_report = {
        "schema_version": "1.0",
        "run_id": run_id,
        "summary": {
            "total_claims": total_claims,
            "passed": passed_count,
            "discrepancy": discrepancy_count,
            "failed": fail_count,
            "pass_rate": round(passed_count / total_claims, 4) if total_claims > 0 else 0.0,
        },
        "results": results,
    }

    report_json = json.dumps(evaluation_report, indent=2)
    hasher.update(report_json.encode("utf-8"))
    publish_artifact(
        run_id=run_id,
        stage="evaluation",
        claim_id=None,
        logical_path="stage_3_evaluation/evaluation_report.json",
        media_type="application/json",
        content=report_json,
        producer_agent_id="evaluator-orchestrator",
    )

    stage_3_manifest_hash = hasher.hexdigest()
    default_run_repo.set_manifest_hash(run_id, "evaluation", stage_3_manifest_hash)

    # Transition run state to EVALUATION_AWAITING_REVIEW
    current_run = default_run_repo.get_run(run_id)
    default_run_repo.transition(
        run_id=run_id,
        expected_version=current_run["version"],
        new_state=RunState.EVALUATION_AWAITING_REVIEW,
        active_stage=None,
    )

    default_broker.emit_stage_update(run_id, "evaluation", "review", progress=100)
    default_broker.emit_activity(
        run_id=run_id,
        stage="evaluation",
        title="Stage 3 complete: Final Review Required",
        detail=f"Evaluated {total_claims} claims: {passed_count} PASS, {discrepancy_count} DISCREPANCY. Final approval required.",
        kind="gate",
        status="done",
    )

    return {
        "status": "EVALUATION_AWAITING_REVIEW",
        "stage_3_manifest_hash": stage_3_manifest_hash,
        "summary": evaluation_report["summary"],
    }
