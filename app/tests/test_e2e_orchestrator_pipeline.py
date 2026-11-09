"""End-to-end integration test for the 3-stage reviewer-gated orchestrator pipeline."""
from pathlib import Path
import pytest

from app.api.runs import create_run, get_run
from app.api.stages import start_stage
from app.api.review import review_stage
from app.api.claims import list_claims, update_claim
from app.api.sections import get_sections
from app.api.sources import list_sources, get_source_knowledge
from app.api.artifacts import list_artifacts, list_claim_artifacts
from app.api.evaluation import get_evaluation
from app.control_plane.run_state import RunState
from app.schemas.claim import ClaimPatch
from app.schemas.messages import StageName
from app.schemas.run import CreateRunRequest, ReviewDecision, StageStartRequest
from app.services.database import default_run_repo


def test_full_three_stage_reviewer_gated_pipeline(tmp_path, monkeypatch):
    """Test full workflow from upload through Stage 1, Review 1, Stage 2, Review 2, Stage 3, and Final Review."""
    # 1. Create Run with sample files
    create_req = CreateRunRequest(
        run_name="Nexipril 2024 PBRER Evaluation",
        target_object_id="sample",
        source_object_ids=["sample"],
        product_name="Nexipril Sodium",
        reporting_period_start="2024-01-01",
        reporting_period_end="2024-12-31",
    )
    run_summary = create_run(create_req)
    run_id = run_summary.run_id
    assert run_summary.status == RunState.READY_FOR_STAGE_1.value
    input_manifest_hash = run_summary.input_manifest_hash

    # 2. Gate invariant check: Stage 2 cannot start before Stage 1 approval
    with pytest.raises(Exception):
        start_stage(
            run_id=run_id,
            stage=StageName.rules,
            payload=StageStartRequest(expected_input_manifest_hash=input_manifest_hash, idempotency_key="k1234567"),
        )

    # 3. Start Stage 1: Claims Orchestrator
    claims_action = start_stage(
        run_id=run_id,
        stage=StageName.claims,
        payload=StageStartRequest(expected_input_manifest_hash=input_manifest_hash, idempotency_key="k1234567"),
    )
    assert claims_action.accepted is True
    assert claims_action.status == RunState.CLAIMS_AWAITING_REVIEW.value

    # Check extracted sections API
    sections = get_sections(run_id)
    assert len(sections) > 0

    # Check sources and source knowledge API
    sources = list_sources(run_id)
    assert len(sources) > 0

    source_knowledge = get_source_knowledge(run_id)
    assert len(source_knowledge["datasets"]) > 0

    # Check claims API
    claims = list_claims(run_id)
    assert len(claims) >= 5

    # Check every claim has an evidence hint
    for c in claims:
        assert "evidence_hint" in c
        assert c["evidence_hint"]["text"]

    # Test updating a claim patch
    target_claim = claims[0]
    patched_claim = update_claim(
        run_id=run_id,
        claim_id=target_claim["claim_id"],
        patch=ClaimPatch(
            expected_version=target_claim["version"],
            reviewer_reason="Verified normalized statement wording",
            normalized_statement=target_claim["normalized_statement"] + " (Reviewer Verified)",
        ),
    )
    assert "(Reviewer Verified)" in patched_claim["normalized_statement"]

    # Check Stage 1 artifacts published
    artifacts = list_artifacts(run_id)
    assert any("source_knowledge" in a["logical_path"] for a in artifacts)

    # 4. Review Gate 1: Human reviewer approves Stage 1
    run_record = default_run_repo.get_run(run_id)
    stage_1_hash = run_record["stage_1_manifest_hash"]

    review_action_1 = review_stage(
        run_id=run_id,
        stage=StageName.claims,
        decision=ReviewDecision(
            decision="approve",
            expected_manifest_hash=stage_1_hash,
            reviewer_note="Stage 1 claims register and hints approved.",
        ),
    )
    assert review_action_1.accepted is True
    assert review_action_1.status == RunState.CLAIMS_APPROVED.value

    # 5. Start Stage 2: Rules Orchestrator
    rules_action = start_stage(
        run_id=run_id,
        stage=StageName.rules,
        payload=StageStartRequest(expected_input_manifest_hash=stage_1_hash, idempotency_key="k8765432"),
    )
    assert rules_action.accepted is True
    assert rules_action.status == RunState.RULES_AWAITING_REVIEW.value

    # Verify claim artifacts produced (plan, rule_spec, analysis.py, result.json, etc.)
    claim_arts = list_claim_artifacts(run_id, target_claim["claim_id"])
    assert any("analysis.py" in a["logical_path"] for a in claim_arts)
    assert any("result.json" in a["logical_path"] for a in claim_arts)

    # 6. Review Gate 2: Human reviewer approves Stage 2
    run_record_2 = default_run_repo.get_run(run_id)
    stage_2_hash = run_record_2["stage_2_manifest_hash"]

    review_action_2 = review_stage(
        run_id=run_id,
        stage=StageName.rules,
        decision=ReviewDecision(
            decision="approve",
            expected_manifest_hash=stage_2_hash,
            reviewer_note="Calculation rules and sandbox results verified.",
        ),
    )
    assert review_action_2.accepted is True
    assert review_action_2.status == RunState.RULES_APPROVED.value

    # 7. Start Stage 3: Evaluator Orchestrator
    eval_action = start_stage(
        run_id=run_id,
        stage=StageName.evaluation,
        payload=StageStartRequest(expected_input_manifest_hash=stage_2_hash, idempotency_key="k9999999"),
    )
    assert eval_action.accepted is True
    assert eval_action.status == RunState.EVALUATION_AWAITING_REVIEW.value

    # Check evaluation outcomes API
    eval_results = get_evaluation(run_id)
    assert len(eval_results) >= 5

    # Verify each evaluation result has all 13 checks
    for ev in eval_results:
        assert len(ev["checks"]) == 13
        assert ev["status"] in ("PASS", "DISCREPANCY")

    # 8. Final Review Gate: Human reviewer final sign-off
    run_record_3 = default_run_repo.get_run(run_id)
    stage_3_hash = run_record_3["stage_3_manifest_hash"]

    final_review = review_stage(
        run_id=run_id,
        stage=StageName.evaluation,
        decision=ReviewDecision(
            decision="approve",
            expected_manifest_hash=stage_3_hash,
            reviewer_note="Final benefit-risk reconciliation dossier signed off.",
        ),
    )
    assert final_review.accepted is True
    assert final_review.status == RunState.COMPLETE.value

    # Confirm run is COMPLETE
    final_summary = get_run(run_id)
    assert final_summary.status == RunState.COMPLETE.value
