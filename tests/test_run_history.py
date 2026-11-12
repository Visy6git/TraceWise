from __future__ import annotations

from fastapi.testclient import TestClient

from app.control_plane.run_state import RunState
from app.main import app


def test_run_history_lists_reopen_metadata(isolated_env, tmp_path):
    target = tmp_path / "report.docx"
    target.write_bytes(b"report")
    run = isolated_env["run_repo"].create_run(
        run_id="run-history-test",
        run_name="Saved PBRER",
        target_object_id=str(target),
        source_object_ids=[],
        product_name="Example product",
        reporting_period_start="2025-01-01",
        reporting_period_end="2025-12-31",
        input_manifest_hash="input-manifest-hash",
    )
    run = isolated_env["run_repo"].transition(
        run_id=run["run_id"],
        expected_version=run["version"],
        new_state=RunState.CLAIMS_RUNNING,
        active_stage="claims",
    )
    run = isolated_env["run_repo"].transition(
        run_id=run["run_id"],
        expected_version=run["version"],
        new_state=RunState.PAUSED,
        active_stage="claims",
    )

    client = TestClient(app)
    history = client.get("/api/runs")
    detail = client.get(f"/api/runs/{run['run_id']}")

    assert history.status_code == 200
    entry = next(item for item in history.json() if item["run_id"] == run["run_id"])
    assert entry["status"] == RunState.PAUSED.value
    assert entry["target_document_filename"] == "report.docx"
    assert entry["product_name"] == "Example product"
    assert entry["reporting_period_start"] == "2025-01-01"
    assert entry["reporting_period_end"] == "2025-12-31"
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run["run_id"]
    assert detail.json()["status"] == RunState.PAUSED.value
