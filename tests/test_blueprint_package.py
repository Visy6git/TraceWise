from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.stages.stage_3_understanding.artifact_builder import (
    prepare_stage3_readonly_inputs, validate_blueprint_package,
)


def test_stage3_inputs_redact_rows_and_tool_transcripts(tmp_path: Path):
    run = tmp_path / "run"
    s1 = run / "stage_1_claims"; s1.mkdir(parents=True)
    s2 = run / "stage_2_rules" / "claims" / "CLM1"; s2.mkdir(parents=True)
    ext = run / "extracted"; ext.mkdir()
    (s1 / "claims_register.v001.json").write_text(json.dumps([{"claim_id":"CLM1","raw_statement":"5 cases","sample_values":["private"]}]))
    (s1 / "source_knowledge.json").write_text(json.dumps({"datasets":[{"dataset_id":"ds1","sample_values":["secret"],"data_columns":["Case ID"]}]}))
    (s2 / "rule_spec.json").write_text(json.dumps({"filters":[],"rows":[{"case":"private"}]}))
    (s2 / "claim_data.json").write_text('{"rows":["private"]}')
    (s2 / "tool_history.jsonl").write_text('{"args":{"patient":"private"}}')
    (ext / "sections.json").write_text("[]")

    out = tmp_path / "stage3-inputs"
    prepare_stage3_readonly_inputs(run, out)
    claim = json.loads((out / "stage_1_claims" / "claims_register.v001.json").read_text())
    rules = json.loads((out / "stage_2_rules" / "claims" / "CLM1" / "rule_spec.json").read_text())
    assert "sample_values" not in claim[0]
    assert "rows" not in rules
    assert not (out / "stage_2_rules" / "claims" / "CLM1" / "claim_data.json").exists()
    assert not (out / "stage_2_rules" / "claims" / "CLM1" / "tool_history.jsonl").exists()


def test_package_validator_finds_missing_runtime_files(tmp_path: Path):
    (tmp_path / "blueprint.json").write_text(json.dumps({"claims": [], "section_structure": [], "status": "draft", "validation": {}}))
    result = validate_blueprint_package(tmp_path)
    assert result["status"] == "blocked"
    assert "reproduce_section.py" in result["missing_files"]


def test_package_validator_does_not_require_its_own_report_before_creating_it(tmp_path: Path):
    required = [
        "section_model.json", "claim_catalog.json", "source_contracts.json",
        "retrieval_policies.json", "transformation_graph.json", "narrative_templates.json",
        "render_spec.json", "schema_drift_policy.json", "reproduce_section.py",
        "tests/test_reproduction_contract.py", "README.md",
    ]
    for name in required:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "{}" if path.suffix == ".json" else "def main():\n    pass\n"
        path.write_text(content, encoding="utf-8")
    (tmp_path / "blueprint.json").write_text(json.dumps({
        "claims": [{"claim_id": "CLM-1"}],
        "section_structure": [{"block_id": "sec-16-3"}],
        "status": "ready_for_review",
        "validation": {"reproduction_tested": True},
    }), encoding="utf-8")
    (tmp_path / "tests" / "test_reproduction_contract.py").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_reproduction_contract.py").write_text(
        "def test_contract():\n    assert True\n", encoding="utf-8",
    )

    result = validate_blueprint_package(tmp_path, isolated_reproduction_test_passed=True)

    assert result["status"] == "structurally_ready_for_reviewer"
    assert "blueprint_validation.json" not in result["missing_files"]


def test_package_validator_does_not_trust_blueprint_test_claim(tmp_path: Path):
    required = [
        "section_model.json", "claim_catalog.json", "source_contracts.json",
        "retrieval_policies.json", "transformation_graph.json", "narrative_templates.json",
        "render_spec.json", "schema_drift_policy.json", "reproduce_section.py", "README.md",
        "tests/test_reproduction_contract.py",
    ]
    for name in required:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path.suffix == ".json" else "content", encoding="utf-8")
    (tmp_path / "blueprint.json").write_text(json.dumps({
        "claims": [{"claim_id": "CLM-1"}],
        "section_structure": [{"block_id": "sec-16-3"}],
        "status": "ready_for_review",
        "validation": {"reproduction_tested": True},
    }), encoding="utf-8")

    result = validate_blueprint_package(tmp_path)

    assert result["status"] == "blocked"
    assert "No isolated reproduction test evidence is recorded." in result["issues"]


def test_approved_incomplete_blueprint_is_flagged_and_cannot_start(isolated_env):
    repo = isolated_env["blueprint_repo"]
    repo.register_candidate(
        blueprint_id="bp-incomplete",
        tenant_id="default",
        source_learning_run_id="learning-incomplete",
        version=1,
        status="needs_review",
        manifest_hash="manifest-hash-incomplete",
        manifest={"files": [{"path": "blueprint.json"}]},
    )
    repo.mark_approved(
        source_learning_run_id="learning-incomplete",
        manifest_hash="manifest-hash-incomplete",
        reviewer_id="reviewer",
    )
    repo.create_generation({
        "generation_id": "generation-incomplete",
        "tenant_id": "default",
        "run_name": "Invalid package",
        "blueprint_id": "bp-incomplete",
        "blueprint_version": 1,
        "status": "failed",
        "reporting_period_start": "2025-01-01",
        "reporting_period_end": "2025-12-31",
        "source_manifest_hash": "source-hash",
        "source_object_ids": [],
    })

    client = TestClient(app)
    listed = client.get("/api/blueprints")
    assert listed.status_code == 200
    blueprint = next(item for item in listed.json() if item["blueprint_id"] == "bp-incomplete")
    assert "reproduce_section.py" in blueprint["generation_error"]

    response = client.post("/api/generations/generation-incomplete/start")
    assert response.status_code == 409
    assert "reproduce_section.py" in response.json()["detail"]
