"""Stage 3: Evaluator Orchestrator independent quality gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.agents.base import AgentRuntimeConfig, build_strands_agent
from app.agents.evaluator_orchestrator.evaluator_tools import rerun_artifact_independently
from app.agents.evaluator_orchestrator.independent_checks import evaluate_claim_independently
from app.config import MOCK_RUNS_ENABLED
from app.control_plane.run_state import RunState
from app.services.bedrock import invoke_bedrock, parse_bedrock_json
from app.services.database import default_claim_repo, default_eval_repo, default_run_repo
from app.services.event_stream import default_broker
from app.services.logging_config import get_run_logger
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

    logger = get_run_logger(run_id, "evaluation")
    logger.info("=== Stage 3 (Evaluation) START | run=%s | mock=%s ===", run_id, MOCK_RUNS_ENABLED)
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
    if not claims:
        raise ValueError(f"No claims found for run {run_id}")

    if MOCK_RUNS_ENABLED:
        source_dir = Path("runtime/sample_pbrer_data").resolve()
        if not source_dir.exists():
            source_dir = default_storage.root_dir / "default" / run_id / "input" / "sources"
    else:
        source_paths = [Path(path).resolve() for path in run.get("source_object_ids", [])]
        if any(
            not path.is_file() or path.suffix.lower() not in {".xlsx", ".csv"}
            for path in source_paths
        ):
            raise FileNotFoundError(
                f"One or more attached XLSX/CSV files are missing for run {run_id}"
            )
        source_files = source_paths
        if not source_files:
            raise FileNotFoundError(f"No real XLSX/CSV source files found for run {run_id}")
        source_dir = source_files[0].parent

    results = []
    hasher = hashlib.sha256()
    processed_count = 0

    for claim in claims:
        claim_id = claim["claim_id"]
        processed_count += 1
        progress = int((processed_count / total_claims) * 90)
        default_broker.emit_stage_update(run_id, "evaluation", "running", progress=progress)

        sub_id = f"eval-{claim_id}"
        sub_name = f"{claim_id} · Independent Evaluator"
        default_broker.emit_subagent_start(
            run_id, "evaluation", sub_id, sub_name, "independent-evaluation",
            detail=f"Independent rerun + audit of Section {claim.get('section_number')}",
        )
        logger.info("Subagent %s START | claim=%s", sub_id, claim_id)
        default_broker.emit_activity(
            run_id=run_id,
            stage="evaluation",
            title=f"Evaluating {claim_id}",
            detail=(
                "Rerunning the generated calculation in a fresh temporary workspace "
                "and checking 13 criteria"
            ),
            kind="tool",
        )

        ws_dir = get_claim_workspace_dir(claim_id, run_id=run_id)

        # Load published Stage 2 artifacts
        rule_bundle: dict[str, Any] = {}
        eb_path = ws_dir / "evidence_bundle.json"
        if eb_path.exists():
            rule_bundle["evidence_bundle"] = json.loads(eb_path.read_text(encoding="utf-8"))
        elif not MOCK_RUNS_ENABLED:
            raise FileNotFoundError(f"Evidence bundle missing for live claim {claim_id}")

        # Perform independent execution in a clean sandbox
        evaluator_run = rerun_artifact_independently(claim_id, run_id=run_id, source_dir=source_dir)

        # Perform independent multi-point checks
        eval_result = evaluate_claim_independently(claim, rule_bundle, evaluator_run)
        eval_dict = eval_result.model_dump()
        if not MOCK_RUNS_ENABLED:
            plan_path = ws_dir / "plan.md"
            spec_path = ws_dir / "rule_spec.json"
            code_path = ws_dir / "analysis.py"
            review_prompt = f"""Review this completed calculation independently.
Do not assume the script is correct because it executed. Check whether its
source selection, filters, entity semantics, period, aggregation, and provenance
are justified by the evidence provided. Numeric agreement alone is not proof.
Return JSON only with: status (PASS, DISCREPANCY, FAIL, INCONCLUSIVE,
NEEDS_HUMAN_REVIEW, or UNRESOLVED), rationale, unresolved_questions.

CLAIM:
{json.dumps(claim, ensure_ascii=False)}

EVIDENCE_BUNDLE:
{json.dumps(rule_bundle, ensure_ascii=False)}

PLAN:
{plan_path.read_text(encoding="utf-8") if plan_path.is_file() else ""}

RULE_SPEC:
{spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""}

ANALYSIS_CODE:
{code_path.read_text(encoding="utf-8") if code_path.is_file() else ""}

INDEPENDENT_RERUN:
{json.dumps(evaluator_run, ensure_ascii=False)}
"""
            model_review = parse_bedrock_json(invoke_bedrock(review_prompt))
            if (
                not isinstance(model_review, dict)
                or not isinstance(model_review.get("rationale"), str)
            ):
                raise ValueError(f"Bedrock evaluator returned an invalid review for {claim_id}")
            allowed_statuses = {
                "PASS", "DISCREPANCY", "FAIL", "INCONCLUSIVE",
                "NEEDS_HUMAN_REVIEW", "UNRESOLVED",
            }
            if model_review.get("status") not in allowed_statuses:
                raise ValueError(f"Bedrock evaluator returned an unknown status for {claim_id}")
            if not isinstance(model_review.get("unresolved_questions", []), list):
                raise ValueError(
                    f"Bedrock evaluator returned invalid unresolved questions for {claim_id}"
                )
            eval_dict["model_review"] = model_review
            unverifiable_checks = {
                "reporting_period",
                "population_and_filters",
                "join_cardinality",
                "deduplication",
                "numerator_denominator",
                "independent_execution",
                "provenance_integrity",
                "source_immutability",
            }
            for check in eval_dict["checks"]:
                if check["category"] in unverifiable_checks:
                    check["status"] = "INCONCLUSIVE"
                    check["summary"] = (
                        "This criterion has not been independently verified in live mode."
                    )
            # A rerun of the same generated code is not an independent method.
            if eval_dict["status"] == "PASS":
                eval_dict["status"] = "NEEDS_HUMAN_REVIEW"
                eval_dict["reviewer_required"] = True
                eval_dict["discrepancy_category"] = "independent_method_not_available"
                eval_dict["model_review"]["rationale"] = (
                    "Same-code rerun is not independent validation. "
                    + model_review["rationale"]
                )
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
        new_status = (
            "pass" if eval_dict["status"] == "PASS"
            else "discrepancy" if eval_dict["status"] == "DISCREPANCY"
            else "needs_review"
        )
        default_claim_repo.update_claim_patch(
            run_id=run_id,
            claim_id=claim_id,
            expected_version=claim.get("version", 1),
            patch={"status": new_status},
            reviewer_reason=f"Stage 3 independent evaluation outcome: {eval_result.status.value}",
            actor_id="evaluator-orchestrator",
        )
        default_broker.emit_claim_update(run_id, claim_id, claim["section_id"], new_status)
        default_broker.emit_subagent_finish(
            run_id, "evaluation", sub_id, sub_name, detail=f"verdict={eval_dict['status']}",
        )
        logger.info("Subagent %s DONE | verdict=%s", sub_id, eval_dict["status"])

    # Compile comprehensive evaluation report
    passed_count = sum(1 for r in results if r["status"] == "PASS")
    discrepancy_count = sum(1 for r in results if r["status"] == "DISCREPANCY")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    review_count = sum(1 for r in results if r["status"] == "NEEDS_HUMAN_REVIEW")

    evaluation_report = {
        "schema_version": "1.0",
        "run_id": run_id,
        "summary": {
            "total_claims": total_claims,
            "passed": passed_count,
            "discrepancy": discrepancy_count,
            "failed": fail_count,
            "needs_human_review": review_count,
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
