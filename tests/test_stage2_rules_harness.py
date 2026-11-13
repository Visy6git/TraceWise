"""Stage 2 rules engineering tests: per-claim Python verification and verified status marking."""
from __future__ import annotations

import csv
import hashlib
import json
from io import StringIO
from pathlib import Path

import pytest

from app.control_plane.run_state import RunState
from app.harness.runner import HarnessRunResult
from app.services.sandbox_client import SandboxClient, SandboxUnavailable
from app.stages.stage_1_claims.orchestrator import run_claims_stage
from app.stages.stage_2_rules import orchestrator as rules_orchestrator
from app.stages.stage_2_rules.orchestrator import run_rules_stage
from tests.conftest import create_synthetic_pbrer_dataset


def test_stage2_verifies_claims_and_marks_verified_in_db_and_events(isolated_env, tmp_path: Path):
    run_repo = isolated_env["run_repo"]
    claim_repo = isolated_env["claim_repo"]
    artifact_repo = isolated_env["artifact_repo"]
    broker = isolated_env["broker"]

    doc_path, source_paths = create_synthetic_pbrer_dataset(tmp_path / "inputs_s2")
    baseline_sha = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}

    h = hashlib.sha256()
    h.update(doc_path.read_bytes())
    for sp in source_paths:
        h.update(sp.read_bytes())
    manifest_hash = h.hexdigest()

    run = run_repo.create_run(
        run_id="run-stage2-test",
        run_name="Stage 2 Verification Run",
        target_object_id=str(doc_path),
        source_object_ids=[str(sp) for sp in source_paths],
        input_manifest_hash=manifest_hash,
    )
    run_repo.transition(
        run_id=run["run_id"],
        expected_version=run["version"],
        new_state=RunState.CLAIMS_RUNNING,
        active_stage="claims",
    )

    s1_res = run_claims_stage(run["run_id"], manifest_hash)
    s1_hash = s1_res["stage_1_manifest_hash"]

    # Approve Stage 1
    r1 = run_repo.get_run(run["run_id"])
    run_repo.record_approval(
        run_id=run["run_id"],
        stage="claims",
        reviewer_id="reviewer-1",
        decision="approve",
        expected_version=r1["version"],
        expected_manifest_hash=s1_hash,
    )
    r2 = run_repo.get_run(run["run_id"])
    run_repo.transition(
        run_id=run["run_id"],
        expected_version=r2["version"],
        new_state=RunState.RULES_RUNNING,
        active_stage="rules",
    )

    # Run Stage 2 per-claim rule verification
    s2_res = run_rules_stage(run["run_id"], s1_hash)
    assert s2_res["status"] == RunState.RULES_AWAITING_REVIEW.value
    assert s2_res["verified_count"] == 2
    assert s2_res["discrepancy_count"] == 0
    assert s2_res["failed_count"] == 0

    # Assert BOTH claims + nested children are marked verified in SQLite
    claims_after = claim_repo.list_claims(run["run_id"])
    assert len(claims_after) == 2
    for c in claims_after:
        assert c["status"] == "verified"
        vr = c["verification_result"]
        assert vr is not None
        assert vr["verified"] is True
        assert vr["status"] == "verified"
        assert vr["result_artifact_id"] is not None
        for child in c["children_claims"]:
            assert child["verified"] is True

    # Verify Stage 2 published analysis.py, result.json, and claim_data.json for each claim
    clm1_arts = artifact_repo.list_artifacts(run["run_id"], claim_id="CLM-0001")
    clm1_paths = {a["logical_path"] for a in clm1_arts}
    assert "stage_2_rules/claims/CLM-0001/analysis.py" in clm1_paths
    assert "stage_2_rules/claims/CLM-0001/result.json" in clm1_paths
    assert "stage_2_rules/claims/CLM-0001/claim_data.json" in clm1_paths

    # Each verified claim exposes its backing source rows for the UI
    for c in claims_after:
        vr = c["verification_result"]
        assert vr["data_available"] is True
        assert vr["data_artifact_id"] is not None

    # The claim-data endpoint returns bounded parent (+children) row tables
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    data_resp = client.get(f"/api/runs/{run['run_id']}/claims/CLM-0001/data")
    assert data_resp.status_code == 200
    payload = data_resp.json()
    assert payload["parent"] is not None
    assert isinstance(payload["parent"]["columns"], list) and payload["parent"]["columns"]
    assert isinstance(payload["parent"]["rows"], list) and payload["parent"]["rows"]
    assert payload["parent"]["row_count"] >= 1
    # Each returned row only carries the declared columns and is JSON-serializable
    assert set(payload["parent"]["rows"][0].keys()) <= set(payload["parent"]["columns"])

    # Raw source sheets are served as bounded UI previews with the full sheet available as CSV.
    src_resp = client.get(f"/api/runs/{run['run_id']}/claims/CLM-0001/source-data")
    assert src_resp.status_code == 200
    src = src_resp.json()
    assert isinstance(src["sheets"], list) and src["sheets"]
    first_sheet = src["sheets"][0]
    assert first_sheet["columns"] and isinstance(first_sheet["rows"], list)
    assert first_sheet["row_count"] >= 1
    assert len(first_sheet["rows"]) <= 500
    assert first_sheet["truncated"] is (first_sheet["row_count"] > len(first_sheet["rows"]))

    preview_resp = client.get(
        f"/api/runs/{run['run_id']}/claims/CLM-0001/source-data",
        params={"limit": 1, "offset": 1},
    )
    assert preview_resp.status_code == 200
    preview_sheet = preview_resp.json()["sheets"][0]
    assert preview_sheet["offset"] == 1
    assert len(preview_sheet["rows"]) <= 1

    csv_params = {"file": first_sheet["source_file"]}
    if first_sheet.get("sheet"):
        csv_params["sheet"] = first_sheet["sheet"]
    csv_resp = client.get(
        f"/api/runs/{run['run_id']}/claims/CLM-0001/source-data.csv",
        params=csv_params,
    )
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "attachment;" in csv_resp.headers["content-disposition"]
    assert next(csv.reader(StringIO(csv_resp.text))) == first_sheet["columns"]

    # Verify AG-UI emitted verified tracewise.claim event
    hist = broker._history[run["run_id"]]
    verified_events = [
        e for e in hist
        if e.get("type") == "CUSTOM"
        and e.get("name") == "tracewise.claim"
        and e.get("value", {}).get("status") == "verified"
    ]
    assert len(verified_events) == 2

    # Confirm source file SHA-256 unchanged
    for p in source_paths:
        assert hashlib.sha256(p.read_bytes()).hexdigest() == baseline_sha[p.name]


def test_stage2_marks_discrepancy_when_reported_mismatch(isolated_env, tmp_path: Path):
    run_repo = isolated_env["run_repo"]
    claim_repo = isolated_env["claim_repo"]

    doc_path, source_paths = create_synthetic_pbrer_dataset(tmp_path / "inputs_mismatch")
    h = hashlib.sha256()
    h.update(doc_path.read_bytes())
    for sp in source_paths:
        h.update(sp.read_bytes())
    manifest_hash = h.hexdigest()

    run = run_repo.create_run(
        run_id="run-stage2-mismatch",
        run_name="Stage 2 Mismatch",
        target_object_id=str(doc_path),
        source_object_ids=[str(sp) for sp in source_paths],
        input_manifest_hash=manifest_hash,
    )
    r = run_repo.get_run(run["run_id"])
    run_repo.transition(run["run_id"], r["version"], RunState.CLAIMS_RUNNING, active_stage="claims")
    s1_res = run_claims_stage(run["run_id"], manifest_hash)
    s1_hash = s1_res["stage_1_manifest_hash"]

    # Tamper reported_value on CLM-0002 (12 -> 999) so Stage 2 detects real mismatch
    c2 = claim_repo.get_claim(run["run_id"], "CLM-0002")
    claim_repo.update_claim_patch(
        run_id=run["run_id"],
        claim_id="CLM-0002",
        expected_version=c2["version"],
        patch={"reported_value": "999"},
        reviewer_reason="Simulate reported mismatch",
    )

    r1 = run_repo.get_run(run["run_id"])
    run_repo.record_approval(run["run_id"], "claims", "rev-1", "approve", r1["version"], s1_hash)
    r2 = run_repo.get_run(run["run_id"])
    run_repo.transition(run["run_id"], r2["version"], RunState.RULES_RUNNING, active_stage="rules")

    s2_res = run_rules_stage(run["run_id"], s1_hash)
    assert s2_res["verified_count"] == 1
    assert s2_res["discrepancy_count"] == 1

    c2_after = claim_repo.get_claim(run["run_id"], "CLM-0002")
    assert c2_after["status"] == "discrepancy"
    assert c2_after["verification_result"]["parent_computed_value"] == 12


def test_stage2_retries_only_the_selected_failed_claim(isolated_env, tmp_path: Path):
    run_repo = isolated_env["run_repo"]
    claim_repo = isolated_env["claim_repo"]
    storage = isolated_env["storage"]

    doc_path, source_paths = create_synthetic_pbrer_dataset(tmp_path / "inputs_targeted_retry")
    manifest_hash = hashlib.sha256(
        doc_path.read_bytes() + b"".join(path.read_bytes() for path in source_paths)
    ).hexdigest()
    run = run_repo.create_run(
        run_id="run-stage2-targeted-retry",
        run_name="Stage 2 Targeted Retry",
        target_object_id=str(doc_path),
        source_object_ids=[str(path) for path in source_paths],
        input_manifest_hash=manifest_hash,
    )
    run_repo.transition(run["run_id"], run["version"], RunState.CLAIMS_RUNNING, active_stage="claims")
    stage_1_result = run_claims_stage(run["run_id"], manifest_hash)

    current = run_repo.get_run(run["run_id"])
    run_repo.record_approval(
        run_id=run["run_id"],
        stage="claims",
        reviewer_id="reviewer-1",
        decision="approve",
        expected_version=current["version"],
        expected_manifest_hash=stage_1_result["stage_1_manifest_hash"],
    )
    current = run_repo.get_run(run["run_id"])
    run_repo.transition(run["run_id"], current["version"], RunState.RULES_RUNNING, active_stage="rules")

    first_claim = claim_repo.get_claim(run["run_id"], "CLM-0001")
    first_claim["status"] = "verified"
    first_claim["verification_result"] = {"verified": True, "status": "verified"}
    claim_repo.save_claim(run["run_id"], first_claim)

    failed_claim = claim_repo.get_claim(run["run_id"], "CLM-0002")
    failed_claim["status"] = "failed"
    failed_claim["verification_result"] = {"verified": False, "status": "failed"}
    claim_repo.save_claim(run["run_id"], failed_claim)

    result = run_rules_stage(
        run["run_id"],
        stage_1_result["stage_1_manifest_hash"],
        claim_id="CLM-0002",
    )

    assert result["verified_count"] == 2
    assert result["discrepancy_count"] == 0
    assert result["failed_count"] == 0
    first_claim_after = claim_repo.get_claim(run["run_id"], "CLM-0001")
    assert first_claim_after["verification_result"] == {
        "verified": True,
        "status": "verified",
    }
    assert claim_repo.get_claim(run["run_id"], "CLM-0002")["status"] == "verified"

    manifest = json.loads(
        storage.read_text(f"default/{run['run_id']}/stage_2_rules/manifest.json")
    )
    assert manifest["verified_count"] == 2
    assert any("CLM-0002" in path for path in manifest["artifact_hashes"])


def test_stage2_persists_harness_diagnostics_when_no_analysis_is_created(
    isolated_env, tmp_path: Path, monkeypatch
):
    run_repo = isolated_env["run_repo"]
    claim_repo = isolated_env["claim_repo"]
    doc_path, source_paths = create_synthetic_pbrer_dataset(tmp_path / "inputs_no_analysis")
    manifest_hash = hashlib.sha256(
        doc_path.read_bytes() + b"".join(path.read_bytes() for path in source_paths)
    ).hexdigest()

    run = run_repo.create_run(
        run_id="run-stage2-no-analysis",
        run_name="Stage 2 No Analysis",
        target_object_id=str(doc_path),
        source_object_ids=[str(path) for path in source_paths],
        input_manifest_hash=manifest_hash,
    )
    run_repo.transition(run["run_id"], run["version"], RunState.CLAIMS_RUNNING, active_stage="claims")
    s1_result = run_claims_stage(run["run_id"], manifest_hash)

    current = run_repo.get_run(run["run_id"])
    run_repo.record_approval(
        run_id=run["run_id"],
        stage="claims",
        reviewer_id="reviewer-1",
        decision="approve",
        expected_version=current["version"],
        expected_manifest_hash=s1_result["stage_1_manifest_hash"],
    )
    current = run_repo.get_run(run["run_id"])
    run_repo.transition(run["run_id"], current["version"], RunState.RULES_RUNNING, active_stage="rules")

    monkeypatch.setattr(rules_orchestrator, "is_live_llm_enabled", lambda: True)
    monkeypatch.setattr(rules_orchestrator, "MOCK_RUNS_ENABLED", False)
    monkeypatch.setattr(
        rules_orchestrator,
        "run_harness_task",
        lambda **_kwargs: HarnessRunResult(
            success=True,
            final_response="I could not start the analysis.",
            turns=1,
            tool_calls_count=0,
            error=None,
        ),
    )

    result = run_rules_stage(run["run_id"], s1_result["stage_1_manifest_hash"])

    assert result["failed_count"] == 2
    claims = claim_repo.list_claims(run["run_id"])
    assert all(
        "without making a tool call" in claim["verification_result"]["discrepancy_summary"]
        for claim in claims
    )
    execution = rules_orchestrator.default_storage.read_text(
        f"default/{run['run_id']}/stage_2_rules/claims/CLM-0001/execution.json"
    )
    assert '"tool_calls_count": 0' in execution
    assert "I could not start the analysis." in execution


def test_sandbox_fails_closed_when_disabled():
    client = SandboxClient(backend="disabled", required=True)
    with pytest.raises(SandboxUnavailable):
        client.execute("run-1", "claim-1", "analysis.py", {})
