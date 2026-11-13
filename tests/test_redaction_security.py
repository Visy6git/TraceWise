"""Security, redaction, and sanitization tests ensuring PHI and secrets do not leak."""
from __future__ import annotations

import io
from fastapi.testclient import TestClient

from app.harness.runner import _sanitize_tool_payload, _sanitize_tool_output
from app.main import app
from app.runtime.generation_service import _validate_output_file, SecurityError
from app.services.blueprint_repository import BlueprintRepository
from app.stages.stage_3_understanding.artifact_builder import _sanitize_sensitive_tree


def test_sanitize_sensitive_tree_phi_removal():
    nested_payload = {
        "claim_id": "CLM-001",
        "section_key": "16.3.1.1",
        "metadata": {
            "title": "Hepatic disorders",
            "rows": [
                {"patient_id": "PT-001", "name": "Secret Patient", "age": 45},
                {"patient_id": "PT-002", "name": "Confidential Case", "age": 52},
            ],
            "sample_rows": [{"id": 1}],
            "records": [{"record": "sensitive"}],
            "patient_data": {"ssn": "000-00-0000"},
            "unique_values": ["val1", "val2"],
            "tool_history": ["Ran command that dumped DB"],
        },
        "children": [
            {
                "claim_id": "CLM-002",
                "raw_rows": [{"bad": "data"}],
                "safe_summary": {"total_count": 235},
            }
        ],
    }

    sanitized = _sanitize_sensitive_tree(nested_payload)

    # Allowed keys preserved
    assert sanitized["claim_id"] == "CLM-001"
    assert sanitized["section_key"] == "16.3.1.1"
    assert sanitized["metadata"]["title"] == "Hepatic disorders"
    assert sanitized["children"][0]["safe_summary"]["total_count"] == 235

    # Sensitive row/patient keys completely removed
    assert "rows" not in sanitized["metadata"]
    assert "sample_rows" not in sanitized["metadata"]
    assert "records" not in sanitized["metadata"]
    assert "patient_data" not in sanitized["metadata"]
    assert "unique_values" not in sanitized["metadata"]
    assert "tool_history" not in sanitized["metadata"]
    assert "raw_rows" not in sanitized["children"][0]


def test_sanitize_tool_payload_redaction_and_bounds():
    # Sensitive keys get replaced with <redacted>
    args = {
        "rows": [{"id": 100}],
        "patient_data": "secret_records",
        "password": "super_secret_pw",
        "token": "api_token_value",
        "safe_flag": True,
    }
    sanitized = _sanitize_tool_payload("shell", args)
    assert sanitized["rows"] == "<redacted>"
    assert sanitized["patient_data"] == "<redacted>"
    assert sanitized["password"] == "<redacted>"
    assert sanitized["token"] == "<redacted>"
    assert sanitized["safe_flag"] is True

    # Truncation of large write_file content
    huge_content = "X" * 1000
    write_args = {"path": "test.txt", "content": huge_content}
    sanitized_write = _sanitize_tool_payload("write_file", write_args)
    assert len(sanitized_write["content"]) < 300
    assert "... <truncated 1000 chars>" in sanitized_write["content"]

    # Tool output bounding
    huge_output = "Y" * 2000
    assert len(_sanitize_tool_output(huge_output)) <= 400


def test_path_traversal_protection(isolated_env):
    client = TestClient(app)
    bp_repo: BlueprintRepository = isolated_env["blueprint_repo"]

    gen_id = "gen-traversal-test"
    bp_repo.create_generation({
        "generation_id": gen_id,
        "tenant_id": "default",
        "run_name": "Traversal Test",
        "blueprint_id": "bp-01",
        "blueprint_version": 1,
        "status": "complete",
        "reporting_period_start": "2026-01-01",
        "reporting_period_end": "2026-12-31",
        "source_manifest_hash": "hash1",
        "source_object_ids": ["src.xlsx"],
    })
    bp_repo.update_generation(
        generation_id=gen_id,
        tenant_id="default",
        artifacts_json=[{
            "artifact_id": "art-evil",
            "logical_path": "../../../etc/passwd",
        }],
    )

    resp = client.get(f"/api/generations/{gen_id}/artifacts/art-evil/content")
    assert resp.status_code == 400
    assert "Invalid artifact path" in resp.json()["detail"]


def test_upload_magic_byte_enforcement(isolated_env):
    client = TestClient(app)
    bp_repo: BlueprintRepository = isolated_env["blueprint_repo"]

    # Register an approved blueprint so upload endpoint accepts it
    bp_repo.register_candidate(
        blueprint_id="bp-upload-sec",
        tenant_id="default",
        source_learning_run_id="run-upload",
        version=1,
        status="candidate_review",
        manifest_hash="hash-sec-12345678",
        manifest={"blueprint_id": "bp-upload-sec", "manifest_sha256": "hash-sec-12345678"},
    )
    bp_repo.mark_approved(
        source_learning_run_id="run-upload",
        manifest_hash="hash-sec-12345678",
        reviewer_id="rev-1",
        tenant_id="default",
    )

    # 1. Fake XLSX with plain text (not PK zip header)
    resp = client.post(
        "/api/generations",
        data={
            "run_name": "Fake XLSX test",
            "blueprint_id": "bp-upload-sec",
            "blueprint_version": "1",
            "reporting_period_start": "2026-01-01",
            "reporting_period_end": "2026-12-31",
        },
        files=[("source_files", ("data.xlsx", io.BytesIO(b"Hello fake excel"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
    )
    assert resp.status_code == 400
    assert "valid XLSX/OpenXML header" in resp.json()["detail"]

    # 2. Executable disguised as CSV (MZ Windows PE header)
    resp = client.post(
        "/api/generations",
        data={
            "run_name": "Executable CSV test",
            "blueprint_id": "bp-upload-sec",
            "blueprint_version": "1",
            "reporting_period_start": "2026-01-01",
            "reporting_period_end": "2026-12-31",
        },
        files=[("source_files", ("exploit.csv", io.BytesIO(b"MZ\x90\x00\x03\x00malicious binary"), "text/csv"))],
    )
    assert resp.status_code == 400
    assert "executable binary" in resp.json()["detail"]


def test_validate_output_file_security_and_format(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    # 1. Escaping file path raises SecurityError
    escaped_file = outside / "escaped.docx"
    escaped_file.write_bytes(b"PK\x03\x04test")
    import pytest
    with pytest.raises(SecurityError, match="escaped the workspace directory boundary"):
        _validate_output_file(escaped_file, "escaped.docx", workspace)

    # 2. File not found
    missing_file = workspace / "missing.json"
    with pytest.raises(RuntimeError, match="missing or not a regular file"):
        _validate_output_file(missing_file, "missing.json", workspace)

    # 3. Empty file
    empty_file = workspace / "empty.docx"
    empty_file.write_bytes(b"")
    with pytest.raises(RuntimeError, match="is empty"):
        _validate_output_file(empty_file, "empty.docx", workspace)

    # 4. Invalid DOCX header
    bad_docx = workspace / "bad.docx"
    bad_docx.write_bytes(b"NOT_A_ZIP")
    with pytest.raises(ValueError, match="not a valid DOCX"):
        _validate_output_file(bad_docx, "bad.docx", workspace)

    # 5. Invalid JSON
    bad_json = workspace / "bad.json"
    bad_json.write_text("{unquoted_bad_json: 123}", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed JSON"):
        _validate_output_file(bad_json, "bad.json", workspace)

    # 6. Valid outputs pass
    good_docx = workspace / "good.docx"
    good_docx.write_bytes(b"PK\x03\x04valid_mock_zip")
    assert _validate_output_file(good_docx, "good.docx", workspace) == b"PK\x03\x04valid_mock_zip"

    good_json = workspace / "good.json"
    good_json.write_text('{"status": "ok"}', encoding="utf-8")
    assert _validate_output_file(good_json, "good.json", workspace) == b'{"status": "ok"}'
