"""Stage 3 placeholder endpoint and orchestrator verification."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.control_plane.run_state import RunState
from app.main import app


def test_stage3_is_explicit_placeholder(isolated_env):
    run_repo = isolated_env["run_repo"]
    run = run_repo.create_run(
        run_id="run-s3-placeholder",
        run_name="Stage 3 Placeholder Check",
        input_manifest_hash="f" * 32,
    )
    run_repo.set_manifest_hash(run["run_id"], "claims", "1" * 32)
    run_repo.set_manifest_hash(run["run_id"], "rules", "2" * 32)
    r1 = run_repo.get_run(run["run_id"])
    run_repo.transition(run["run_id"], r1["version"], RunState.CLAIMS_RUNNING, active_stage="claims")
    r2 = run_repo.get_run(run["run_id"])
    run_repo.transition(run["run_id"], r2["version"], RunState.CLAIMS_AWAITING_REVIEW)
    r3 = run_repo.get_run(run["run_id"])
    run_repo.record_approval(run["run_id"], "claims", "rev-1", "approve", r3["version"], "1" * 32)
    r4 = run_repo.get_run(run["run_id"])
    run_repo.transition(run["run_id"], r4["version"], RunState.RULES_RUNNING, active_stage="rules")
    r5 = run_repo.get_run(run["run_id"])
    run_repo.transition(run["run_id"], r5["version"], RunState.RULES_AWAITING_REVIEW)
    r6 = run_repo.get_run(run["run_id"])
    run_repo.record_approval(run["run_id"], "rules", "rev-1", "approve", r6["version"], "2" * 32)

    client = TestClient(app)

    # POST /stages/evaluation/start returns placeholder and does NOT crash or transition run to RUNNING
    resp = client.post(
        f"/api/runs/{run['run_id']}/stages/evaluation/start",
        json={"expected_input_manifest_hash": "2" * 32, "idempotency_key": "k-stage3-test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "placeholder"
    assert body["accepted"] is False
    assert "placeholder" in body["message"].lower()

    after_run = run_repo.get_run(run["run_id"])
    assert after_run["status"] == RunState.RULES_APPROVED.value

    # GET /stage-3/evaluation explicitly advertises placeholder status
    get_resp = client.get(f"/api/runs/{run['run_id']}/stage-3/evaluation")
    assert get_resp.status_code == 200
    ev = get_resp.json()
    assert ev["is_placeholder"] is True
    assert ev["status"] == "placeholder"

