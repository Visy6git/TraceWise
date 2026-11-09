import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from app.agents.claims_orchestrator import agent as claims_agent
from app.api import runs
from app.main import app
from app.schemas.run import CreateRunRequest
from app.services import bedrock
from app.services.database import Database, RunRepository
from app.services.storage import StorageService


def test_live_json_run_cannot_fall_back_to_sample_data(monkeypatch):
    monkeypatch.setattr(runs, "MOCK_RUNS_ENABLED", False)
    request = CreateRunRequest(
        run_name="Live run",
        target_object_id="sample",
        source_object_ids=["sample"],
    )

    with pytest.raises(HTTPException) as error:
        runs.create_run(request)

    assert error.value.status_code == 409


def test_live_upload_stores_only_received_files(tmp_path, monkeypatch):
    storage = StorageService(tmp_path / "objects")
    repository = RunRepository(Database(tmp_path / "runs.sqlite"))
    monkeypatch.setattr(runs, "MOCK_RUNS_ENABLED", False)
    monkeypatch.setattr(runs, "MAX_UPLOAD_MB", 1)
    monkeypatch.setattr(runs, "default_storage", storage)
    monkeypatch.setattr(runs, "default_run_repo", repository)

    response = TestClient(app).post(
        "/api/runs/upload",
        data={"run_name": "Live test"},
        files=[
            (
                "target_file",
                (
                    "report.docx",
                    b"real report bytes",
                    "application/vnd.openxmlformats."
                    "officedocument.wordprocessingml.document",
                ),
            ),
            (
                "source_files",
                (
                    "source.xlsx",
                    b"real workbook bytes",
                    "application/vnd.openxmlformats."
                    "officedocument.spreadsheetml.sheet",
                ),
            ),
            ("source_files", ("source.csv", b"id,value\n1,2\n", "text/csv")),
        ],
    )

    assert response.status_code == 201
    run = repository.get_run(response.json()["run_id"])
    assert run is not None
    assert Path(run["target_object_id"]).read_bytes() == b"real report bytes"
    assert [Path(path).name for path in run["source_object_ids"]] == ["source.xlsx", "source.csv"]
    assert all(Path(path).is_file() for path in run["source_object_ids"])


def test_live_upload_rejects_unsupported_source_type(monkeypatch):
    monkeypatch.setattr(runs, "MOCK_RUNS_ENABLED", False)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            runs.upload_run(
                run_name="Live test",
                target_file=UploadFile(filename="report.docx", file=BytesIO(b"docx")),
                source_files=[UploadFile(filename="source.pdf", file=BytesIO(b"pdf"))],
            )
        )
    assert error.value.status_code == 400
    assert ".csv" in error.value.detail


def test_live_claim_extraction_for_section_16_3_subsection(monkeypatch):
    import logging

    monkeypatch.setattr(
        claims_agent,
        "invoke_bedrock",
        lambda prompt, **_: """{"claims":[{"block_id":"block-1",
        "raw_statement":"A total of 164 cases of cardiac failure were retrieved.",
        "normalized_statement":"164 distinct cardiac failure cases.","claim_type":"distinct_case_count",
        "entity_unit":"case","reported_value":164,"unit":"cases",
        "reporting_period":{"value":"cumulative","evidence_status":"observed"},
        "population":{"value":null,"evidence_status":"unknown"},
        "evidence_hint":{"text":"Count distinct Case Number in the Cardiac failure CSMR case sheet.",
        "observed":[],"inferred":[],"unknowns":[],"source_refs":["03_case_Cardiac failure_CSMR.xlsx"]},
        "verification_plan":{"source_file":"03_case_Cardiac failure_CSMR.xlsx","sheet":"CSMR Case_2",
        "header_row_index":5,"columns":["Case Number"],"filters":[],"dedup_key":"Case Number",
        "aggregation":"distinct count of Case Number","expected_value":"164"}}]}""",
    )
    unit = {
        "section_id": "sec_16_3_1_1",
        "section_number": "16.3.1.1",
        "title": "Cardiac failure",
        "level": 2,
        "keywords": ["cardiac", "failure"],
        "blocks": [{
            "block_id": "block-1",
            "type": "paragraph",
            "text": "A total of 164 cases of cardiac failure were retrieved.",
            "paragraph_index": 12,
        }],
    }
    claims = claims_agent._extract_claims_for_unit(
        unit,
        {"sources": [], "datasets": [], "columns": [], "relationships": []},
        matched_filenames=["03_case_Cardiac failure_CSMR.xlsx"],
        doc_filename="report.docx",
        start_seq=1,
        logger=logging.getLogger("test"),
    )

    assert len(claims) == 1
    assert claims[0].claim_id == "CLM-0001"
    assert claims[0].section_number == "16.3.1.1"
    assert claims[0].target_locator.block_id == "block-1"
    assert claims[0].reported_value in (164, "164", 164.0)
    vp = claims[0].evidence_hint.verification_plan
    assert vp is not None and vp.sheet == "CSMR Case_2" and vp.header_row_index == 5
    assert vp.dedup_key == "Case Number"


def test_live_claim_extraction_rejects_missing_claims_array(monkeypatch):
    import logging

    monkeypatch.setattr(claims_agent, "invoke_bedrock", lambda prompt, **_: '{"not_claims": []}')
    unit = {
        "section_id": "sec_16_3_1_1", "section_number": "16.3.1.1", "title": "Cardiac failure",
        "level": 2, "keywords": [], "blocks": [{"block_id": "b1", "type": "paragraph", "text": "x" * 50}],
    }
    with pytest.raises(ValueError, match="claims array"):
        claims_agent._extract_claims_for_unit(
            unit, {"sources": [], "datasets": []}, matched_filenames=[],
            doc_filename="report.docx", start_seq=1, logger=logging.getLogger("test"),
        )


def test_bedrock_converse_errors_are_not_replaced_with_mock_success(monkeypatch):
    class FakeClient:
        def converse(self, **kwargs):
            assert kwargs["modelId"] == "test-model"
            assert kwargs["inferenceConfig"] == {"maxTokens": 8192}
            return {"output": {"message": {"content": [{"text": "real response"}]}}}

    monkeypatch.setattr(bedrock, "BEDROCK_ENABLED", True)
    monkeypatch.setattr(bedrock, "BEDROCK_MODEL_ID", "test-model")
    monkeypatch.setattr(bedrock, "get_boto3_bedrock_client", lambda region=None: FakeClient())

    assert bedrock.invoke_bedrock("test prompt") == "real response"
    assert bedrock.parse_bedrock_json('```json\n{"ok": true}\n```') == {"ok": True}
