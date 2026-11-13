from __future__ import annotations

import json
from pathlib import Path
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
