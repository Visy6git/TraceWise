"""FastAPI routes, file uploads, /api/config, and artifact/markdown content serving tests."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import runs
from app.control_plane.run_state import RunState
from app.main import app
from app.stages.stage_1_claims.orchestrator import run_claims_stage
from tests.conftest import create_synthetic_pbrer_dataset


def test_health_and_config_endpoints(isolated_env):
    client = TestClient(app)
    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["stage_3_placeholder"] is True

    r_cfg = client.get("/api/config")
    assert r_cfg.status_code == 200
    cfg = r_cfg.json()
    assert cfg["status"] == "ok"
    assert cfg["stage_3_placeholder"] is True


def test_live_json_run_blocks_sample_fallback(isolated_env, monkeypatch):
    monkeypatch.setattr(runs, "MOCK_RUNS_ENABLED", False)
    client = TestClient(app)
    resp = client.post(
        "/api/runs",
        json={
            "run_name": "Should fail in live",
            "target_object_id": "sample",
            "source_object_ids": ["sample"],
        },
    )
    assert resp.status_code == 409


def test_upload_validation_and_artifact_content_endpoints(isolated_env, tmp_path: Path):
    client = TestClient(app)

    # Reject invalid source file extension (.pdf)
    bad = client.post(
        "/api/runs/upload",
        data={"run_name": "Bad upload"},
        files=[
            ("target_file", ("report.docx", b"docx bytes", "application/octet-stream")),
            ("source_files", ("bad.pdf", b"pdf bytes", "application/pdf")),
        ],
    )
    assert bad.status_code == 400
    assert ".csv" in bad.json()["detail"]

    # Upload genuine synthetic DOCX + XLSX + CSV bytes and verify content endpoints
    doc_path, source_paths = create_synthetic_pbrer_dataset(tmp_path / "upload_src")
    resp = client.post(
        "/api/runs/upload",
        data={"run_name": "Real Upload Run"},
        files=[
            ("target_file", (doc_path.name, doc_path.read_bytes(), "application/octet-stream")),
            ("source_files", (source_paths[0].name, source_paths[0].read_bytes(), "application/octet-stream")),
            ("source_files", (source_paths[1].name, source_paths[1].read_bytes(), "text/csv")),
        ],
    )
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    input_hash = resp.json()["input_manifest_hash"]

    # Run Stage 1 and test content retrieval endpoints
    r = isolated_env["run_repo"].get_run(run_id)
    isolated_env["run_repo"].transition(run_id, r["version"], RunState.CLAIMS_RUNNING, active_stage="claims")
    run_claims_stage(run_id, input_hash)

    # Master summary endpoint
    r_master = client.get(f"/api/runs/{run_id}/stage-1/master-summary")
    assert r_master.status_code == 200
    assert "Master Summary of Source Documents" in r_master.json()["content"]

    # Per-source summary endpoint
    r_src_md = client.get(f"/api/runs/{run_id}/stage-1/sources/{source_paths[0].name}/summary")
    assert r_src_md.status_code == 200
    assert "01_Hepatic_CSMR.xlsx" in r_src_md.json()["content"]

    # Artifact content endpoint (both .py and .md)
    arts = client.get(f"/api/runs/{run_id}/artifacts").json()
    py_art = next(a for a in arts if a["logical_path"].endswith("_explore.py"))
    r_content = client.get(f"/api/runs/{run_id}/artifacts/{py_art['artifact_id']}/content")
    assert r_content.status_code == 200
    assert "SOURCE_CATALOG" in r_content.json()["content"]

