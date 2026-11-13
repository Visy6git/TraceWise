"""API tests for Stage 3 Understanding and legacy evaluation deprecation."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.control_plane.run_state import RunState
from app.main import app
from app.services.blueprint_repository import BlueprintRepository
from app.services.database import RunRepository


def test_legacy_stage_evaluation_start_deprecated(isolated_env):
    client = TestClient(app)
    run_repo: RunRepository = isolated_env["run_repo"]

    # Create dummy run
    run_id = "test-legacy-run-1"
    run_repo.create_run(
        run_id=run_id,
        run_name="Legacy Evaluation Test",
        target_object_id="target-1",
        source_object_ids=["source-1"],
        input_manifest_hash="input-hash-12345678",
    )

    resp = client.post(
        f"/api/runs/{run_id}/stages/evaluation/start",
        json={
            "expected_input_manifest_hash": "stage-2-hash-12345678",
            "idempotency_key": "idemp-key-1234",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] is False
    assert data["status"] == "placeholder"
    assert "/stages/understanding/start" in data["message"]


def test_start_understanding_preconditions(isolated_env):
    client = TestClient(app)
    run_repo: RunRepository = isolated_env["run_repo"]

    # 404 on nonexistent run
    resp = client.post(
        "/api/runs/nonexistent-run/stages/understanding/start",
        json={
            "expected_input_manifest_hash": "stage-2-hash-12345678",
            "idempotency_key": "idemp-key-1234",
        },
    )
    assert resp.status_code == 404

    # Create run in READY_FOR_STAGE_1 state
    run_id = "run-preconditions-1"
    run_repo.create_run(
        run_id=run_id,
        run_name="Stage 3 Preconditions",
        target_object_id="target-1",
        source_object_ids=["source-1"],
        input_manifest_hash="input-hash-12345678",
    )

    # Empty/short idempotency key -> 422
    resp = client.post(
        f"/api/runs/{run_id}/stages/understanding/start",
        json={
            "expected_input_manifest_hash": "stage-2-hash-12345678",
            "idempotency_key": "short",
        },
    )
    assert resp.status_code == 422

    # Run is in READY_FOR_STAGE_1 state, not RULES_APPROVED -> 409
    resp = client.post(
        f"/api/runs/{run_id}/stages/understanding/start",
        json={
            "expected_input_manifest_hash": "stage-2-hash-12345678",
            "idempotency_key": "idemp-key-1234",
        },
    )
    assert resp.status_code == 409

    # Advance run to RULES_APPROVED with a specific stage_2_manifest_hash
    run = run_repo.get_run(run_id)
    run_repo.transition(
        run_id, run["version"], RunState.CLAIMS_RUNNING, active_stage="claims",
    )
    run = run_repo.get_run(run_id)
    run_repo.transition(
        run_id, run["version"], RunState.CLAIMS_AWAITING_REVIEW, active_stage="claims",
    )
    run_repo.set_manifest_hash(run_id, "claims", "s1_hash_1234567890")
    run = run_repo.get_run(run_id)
    run_repo.record_approval(
        run_id, "claims", "rev-1", "approve", run["version"], "s1_hash_1234567890",
    )
    run = run_repo.get_run(run_id)
    run_repo.transition(
        run_id, run["version"], RunState.RULES_RUNNING, active_stage="rules",
    )
    run = run_repo.get_run(run_id)
    run_repo.transition(
        run_id, run["version"], RunState.RULES_AWAITING_REVIEW, active_stage="rules",
    )
    run_repo.set_manifest_hash(run_id, "rules", "correct-stage-2-hash-1234")
    run = run_repo.get_run(run_id)
    run_repo.record_approval(
        run_id, "rules", "rev-1", "approve", run["version"], "correct-stage-2-hash-1234",
    )

    # Passing stale hash -> 409
    resp = client.post(
        f"/api/runs/{run_id}/stages/understanding/start",
        json={
            "expected_input_manifest_hash": "stale-stage-2-hash-0000",
            "idempotency_key": "idemp-key-1234",
        },
    )
    assert resp.status_code == 409
    assert "stale" in resp.json()["detail"].lower()


def test_review_understanding_manifest_verification(isolated_env, monkeypatch):
    client = TestClient(app)
    run_repo: RunRepository = isolated_env["run_repo"]
    bp_repo: BlueprintRepository = isolated_env["blueprint_repo"]

    run_id = "run-review-test-1"
    run_repo.create_run(
        run_id=run_id,
        run_name="Review Verification Run",
        target_object_id="target-1",
        source_object_ids=["source-1"],
        input_manifest_hash="input-hash-12345678",
    )
    # Transition to EVALUATION_AWAITING_REVIEW
    run = run_repo.get_run(run_id)
    run_repo.transition(
        run_id, run["version"], RunState.CLAIMS_RUNNING, active_stage="claims",
    )
    run = run_repo.get_run(run_id)
    run_repo.transition(
        run_id, run["version"], RunState.CLAIMS_AWAITING_REVIEW, active_stage="claims",
    )
    run_repo.set_manifest_hash(run_id, "claims", "s1_hash_1234567890")
    run = run_repo.get_run(run_id)
    run_repo.record_approval(
        run_id, "claims", "rev-1", "approve", run["version"], "s1_hash_1234567890",
    )
    run = run_repo.get_run(run_id)
    run_repo.transition(
        run_id, run["version"], RunState.RULES_RUNNING, active_stage="rules",
    )
    run = run_repo.get_run(run_id)
    run_repo.transition(
        run_id, run["version"], RunState.RULES_AWAITING_REVIEW, active_stage="rules",
    )
    run_repo.set_manifest_hash(run_id, "rules", "correct-stage-2-hash-1234")
    run = run_repo.get_run(run_id)
    run_repo.record_approval(
        run_id, "rules", "rev-1", "approve", run["version"], "correct-stage-2-hash-1234",
    )
    run = run_repo.get_run(run_id)
    run_repo.transition(
        run_id, run["version"], RunState.EVALUATION_RUNNING, active_stage="evaluation",
    )
    run = run_repo.get_run(run_id)
    run_repo.transition(
        run_id, run["version"], RunState.EVALUATION_AWAITING_REVIEW, active_stage="evaluation",
    )

    # Attempt to approve when no candidate blueprint exists -> 409
    resp = client.post(
        f"/api/runs/{run_id}/stages/understanding/review",
        json={
            "decision": "approve",
            "expected_manifest_hash": "candidate-hash-abc-1234",
            "reviewer_note": "LGTM",
        },
    )
    assert resp.status_code == 409
    assert "No Stage 3 blueprint candidate found" in resp.json()["detail"]

    # Register candidate with different hash
    bp_repo.register_candidate(
        blueprint_id="bp-test-rev",
        tenant_id="default",
        source_learning_run_id=run_id,
        version=1,
        status="candidate_review",
        manifest_hash="actual-candidate-hash-1234",
        manifest={"blueprint_id": "bp-test-rev", "manifest_sha256": "actual-candidate-hash-1234"},
    )

    # Attempt to approve with mismatched expected hash -> 409
    resp = client.post(
        f"/api/runs/{run_id}/stages/understanding/review",
        json={
            "decision": "approve",
            "expected_manifest_hash": "wrong-hash-12345678",
            "reviewer_note": "LGTM",
        },
    )
    assert resp.status_code == 409
    assert "Blueprint manifest mismatch" in resp.json()["detail"]

    # Approve with exact matching hash -> 200
    resp = client.post(
        f"/api/runs/{run_id}/stages/understanding/review",
        json={
            "decision": "approve",
            "expected_manifest_hash": "actual-candidate-hash-1234",
            "reviewer_note": "Approved!",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] is True
    assert data["blueprint"]["status"] == "approved"
