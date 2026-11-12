from __future__ import annotations

from fastapi.testclient import TestClient

from app.control_plane.run_state import RunState, validate_stage_start
from app.main import app


def test_approving_claims_unlocks_stage_two(isolated_env):
    run_repo = isolated_env["run_repo"]
    run = run_repo.create_run(
        run_id="run-review-stage-one",
        run_name="Review Stage One",
        target_object_id="target.docx",
        source_object_ids=["source.xlsx"],
        input_manifest_hash="input-manifest-hash-1234",
    )
    run_repo.transition(
        run_id=run["run_id"],
        expected_version=run["version"],
        new_state=RunState.CLAIMS_RUNNING,
        active_stage="claims",
    )
    manifest_hash = "stage-one-manifest-hash-1234"
    run_repo.set_manifest_hash(run["run_id"], "claims", manifest_hash)
    running = run_repo.get_run(run["run_id"])
    run_repo.transition(
        run_id=run["run_id"],
        expected_version=running["version"],
        new_state=RunState.CLAIMS_AWAITING_REVIEW,
        active_stage=None,
    )

    response = TestClient(app).post(
        f"/api/runs/{run['run_id']}/stages/claims/review",
        json={"decision": "approve", "expected_manifest_hash": manifest_hash},
    )

    assert response.status_code == 200
    assert response.json()["status"] == RunState.CLAIMS_APPROVED.value
    validate_stage_start(RunState(response.json()["status"]), "rules")


def _drive_to(run_repo, run_id: str, *states):
    for state, active in states:
        cur = run_repo.get_run(run_id)
        run_repo.transition(run_id, cur["version"], state, active_stage=active)


def test_rerun_rejected_while_stage_is_running(isolated_env):
    run_repo = isolated_env["run_repo"]
    run = run_repo.create_run(
        run_id="run-rerun-running",
        run_name="Rerun Running",
        target_object_id="target.docx",
        source_object_ids=["source.xlsx"],
        input_manifest_hash="input-manifest-hash-1234",
    )
    s1 = "stage-one-manifest-hash-0001"
    run_repo.set_manifest_hash(run["run_id"], "claims", s1)
    _drive_to(
        run_repo,
        run["run_id"],
        (RunState.CLAIMS_RUNNING, "claims"),
        (RunState.CLAIMS_AWAITING_REVIEW, None),
        (RunState.CLAIMS_APPROVED, None),
        (RunState.RULES_RUNNING, "rules"),
    )
    # Rerun must not be allowed while the stage is actively running (no thread spawned).
    response = TestClient(app).post(
        f"/api/runs/{run['run_id']}/stages/rules/rerun",
        json={"expected_input_manifest_hash": s1, "idempotency_key": "idem-key-1234"},
    )
    assert response.status_code == 409


def test_rerun_rejected_with_stale_manifest(isolated_env):
    run_repo = isolated_env["run_repo"]
    run = run_repo.create_run(
        run_id="run-rerun-stale",
        run_name="Rerun Stale",
        target_object_id="target.docx",
        source_object_ids=["source.xlsx"],
        input_manifest_hash="input-manifest-hash-1234",
    )
    run_repo.set_manifest_hash(run["run_id"], "claims", "stage-one-manifest-hash-0001")
    _drive_to(
        run_repo,
        run["run_id"],
        (RunState.CLAIMS_RUNNING, "claims"),
        (RunState.FAILED, "claims"),
    )
    response = TestClient(app).post(
        f"/api/runs/{run['run_id']}/stages/claims/rerun",
        json={"expected_input_manifest_hash": "wrong-manifest-hash-9999", "idempotency_key": "idem-key-1234"},
    )
    assert response.status_code == 409
