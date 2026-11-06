"""Comprehensive integration and unit test suite for TraceWise Phase 2 Architecture.
Tests:
- Full dataset profiling beyond 100 rows
- Header discovery with metadata rows
- Relationship discovery & join cardinality analysis
- Claim atomization (one claim per figure)
- Evidence retrieval with full dataset coordinates
- Distinct entity counting (cases vs events)
- Validator rejection & reconciliation
- Bounded 3-retry loop ending in UNRESOLVED
- Reviewer note targeted retry
- Source immutability & read-only protection
- Multi-tenant isolation
- AG-UI event replay
- Bedrock multi-turn tool interaction loop
"""
from __future__ import annotations
import io
import json
from pathlib import Path
import openpyxl
import pytest

from app.schemas.claim import Claim
from app.schemas.evidence import EvidenceBundle
from app.schemas.metric_rule import MetricRule, MetricFilter
from app.schemas.validation import ValidationResult
from app.services.execution_engine import ExecutionEngine
from app.services.sandbox import AgentSandbox
from app.services.ag_ui import AGUIEventManager
from app.services.bedrock import converse_with_tools
from app.agents.explorer.agent import ExplorerAgent
from app.agents.claims.agent import ClaimsAgent
from app.agents.evidence.agent import EvidenceDiscoveryAgent
from app.agents.rule_engineer.agent import RuleEngineerAgent
from app.agents.validator.agent import ValidatorAgent
from app.agents.orchestrator.agent import MultiAgentOrchestrator


def create_sample_workbook(path: Path, rows_count: int = 250, with_metadata_header: bool = False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Events"
    if with_metadata_header:
        ws.append(["CONFIDENTIAL PHARMACOVIGILANCE REPORT"])
        ws.append(["Extract Date: 2024-01-01", "Filter: All Spontaneous"])
        ws.append([])  # blank row

    ws.append(["Case Number", "Event PT", "Source", "Receipt Date", "Derived-Initial-Follow-up-Flag"])
    for i in range(1, rows_count + 1):
        case_id = f"CASE-{((i - 1) // 3) + 1:04d}"  # 3 events per case
        pt = "Cardiac failure" if i % 5 == 0 else "Binge eating" if i % 7 == 0 else "Headache"
        source = "Spontaneous" if i % 2 == 0 else "Clinical Trial"
        ws.append([case_id, pt, source, "20240115", "Initial" if i % 3 == 1 else "Follow-up"])
    wb.save(path)


def test_full_worksheet_profiling_beyond_100_rows(tmp_path):
    excel_path = tmp_path / "large_events.xlsx"
    create_sample_workbook(excel_path, rows_count=350)

    engine = ExecutionEngine(tmp_path)
    try:
        engine.ingest_source_file(excel_path, "large_events.xlsx")
        tables = engine.list_tables()
        assert len(tables) == 1
        tbl = tables[0]
        # Must profile all 350 rows, NOT capped at 100!
        assert tbl["row_count"] == 350

        # Profile columns
        case_col = next(c for c in tbl["columns"] if "case" in c)
        prof = engine.profile_column(tbl["table_name"], case_col)
        assert prof["total_rows"] == 350
        assert prof["distinct_count"] == ((350 - 1) // 3) + 1
        assert prof["null_count"] == 0
    finally:
        engine.close()


def test_header_discovery_with_metadata_rows(tmp_path):
    excel_path = tmp_path / "metadata_events.xlsx"
    create_sample_workbook(excel_path, rows_count=50, with_metadata_header=True)

    engine = ExecutionEngine(tmp_path)
    try:
        engine.ingest_source_file(excel_path, "metadata_events.xlsx")
        tables = engine.list_tables()
        assert len(tables) == 1
        cols = tables[0]["columns"]
        # Must discover real column headers despite title rows at the top
        assert any("case" in c.lower() for c in cols)
        assert any("event" in c.lower() for c in cols)
    finally:
        engine.close()


def test_relationship_discovery_and_cardinality(tmp_path):
    # 1. Case table (1-to-1 per case)
    case_path = tmp_path / "cases.xlsx"
    wb1 = openpyxl.Workbook()
    ws1 = wb1.active
    ws1.title = "Cases"
    ws1.append(["Case Number", "Patient Age", "Country"])
    for i in range(1, 21):
        ws1.append([f"CASE-{i:04d}", 45 + (i % 20), "US"])
    wb1.save(case_path)

    # 2. Event table (multiple events per case: 1-to-many)
    event_path = tmp_path / "events.xlsx"
    wb2 = openpyxl.Workbook()
    ws2 = wb2.active
    ws2.title = "Events"
    ws2.append(["Case Number", "Event PT", "Outcome"])
    for i in range(1, 61):
        ws2.append([f"CASE-{(i % 20) + 1:04d}", "Nausea", "Recovered"])
    wb2.save(event_path)

    engine = ExecutionEngine(tmp_path)
    try:
        engine.ingest_source_file(case_path, "cases.xlsx")
        engine.ingest_source_file(event_path, "events.xlsx")

        joins = engine.find_candidate_joins()
        assert len(joins) >= 1
        j = joins[0]
        assert j["overlapping_keys"] == 20
        # Cardinality must be discovered as one_to_many or many_to_one
        assert j["cardinality"] in ("one_to_many", "many_to_one")
    finally:
        engine.close()


def test_claim_atomization_multiple_figures():
    text = (
        "A total of 242 cases were identified in the reporting period "
        "(225 spontaneous, 17 from other studies). The most frequent terms were "
        "pathological gambling (32), binge eating (38), and hypersexuality (24)."
    )
    agent = ClaimsAgent(
        run_id="test-run",
        section_id="sec-16.3.1.1",
        section_number="16.3.1.1",
        section_title="Impulse Control Disorders",
    )
    claims = agent.extract_claims(text)

    # Decomposes into distinct individual claims: total cases, splits, preferred terms
    assert len(claims) >= 5
    claim_types = [c.claim_type for c in claims]
    assert "total_cases" in claim_types
    assert "source_split" in claim_types
    assert "preferred_term" in claim_types

    total_claim = next(c for c in claims if c.claim_type == "total_cases")
    assert total_claim.reported_value == "242"
    assert total_claim.numeric_value == 242.0

    spont_claim = next(c for c in claims if "spontaneous" in c.normalized_statement.lower())
    assert spont_claim.reported_value == "225"


def test_distinct_entity_counting_vs_event_records(tmp_path):
    excel_path = tmp_path / "counts.xlsx"
    create_sample_workbook(excel_path, rows_count=60)  # 20 distinct cases (3 events per case)

    engine = ExecutionEngine(tmp_path)
    try:
        engine.ingest_source_file(excel_path, "counts.xlsx")
        table_name = engine.list_tables()[0]["table_name"]

        rule = MetricRule(
            rule_id="RULE-DISTINCT-TEST",
            claim_id="CLM-01",
            source_table=table_name,
            entity_identifier="case_number",
            aggregation="distinct_count",
        )
        res = engine.compile_and_execute_rule(rule)
        assert res.status == "success"
        # 60 total rows, but exactly 20 distinct cases!
        assert res.distinct_entities == 20
        assert res.evidence_row_count == 60
    finally:
        engine.close()


def test_validator_detects_reconciliation_mismatch(tmp_path):
    engine = ExecutionEngine(tmp_path)
    try:
        claim = Claim(
            claim_id="CLM-TEST-RECON",
            section_id="sec-16.3.1.1",
            section_number="16.3.1.1",
            raw_text="A total of 242 cases were reported",
            normalized_statement="Total cases",
            reported_value="242",
            numeric_value=242.0,
        )
        evidence = EvidenceBundle(
            claim_id=claim.claim_id,
            candidate_datasets=["tbl_test"],
            total_matching_rows=229,
        )
        rule = MetricRule(
            rule_id="RULE-TEST",
            claim_id=claim.claim_id,
            source_table="tbl_test",
            entity_identifier="case_number",
        )
        # Discrepant result: 229 vs reported 242
        from app.schemas.metric_rule import MetricResult
        result = MetricResult(
            computed_value=229,
            numeric_value=229.0,
            status="success",
        )

        validator = ValidatorAgent("test-run", engine)
        val_res = validator.validate_claim(claim, evidence, rule, result, attempt=1)

        assert val_res.status == "RETRY_NEEDED"
        assert not val_res.reconciled
        assert "242" in val_res.discrepancy and "229" in val_res.discrepancy
        assert val_res.target_stage_for_retry == "rule_engineer"
    finally:
        engine.close()


def test_bounded_three_retries_marks_unresolved(tmp_path):
    engine = ExecutionEngine(tmp_path)
    try:
        claim = Claim(
            claim_id="CLM-RETRY-TEST",
            section_id="sec-16.3.1.1",
            section_number="16.3.1.1",
            raw_text="Reported 100 cases",
            normalized_statement="Total cases",
            reported_value="100",
            numeric_value=100.0,
        )
        evidence = EvidenceBundle(claim_id=claim.claim_id, candidate_datasets=["tbl_x"], total_matching_rows=50)
        rule = MetricRule(rule_id="R-1", claim_id=claim.claim_id, source_table="tbl_x", entity_identifier="case_id")
        from app.schemas.metric_rule import MetricResult
        mismatch_res = MetricResult(computed_value=50, numeric_value=50.0, status="success")

        validator = ValidatorAgent("test-run", engine)

        # Attempt 1 -> RETRY_NEEDED
        r1 = validator.validate_claim(claim, evidence, rule, mismatch_res, attempt=1)
        assert r1.status == "RETRY_NEEDED"

        # Attempt 2 -> RETRY_NEEDED
        r2 = validator.validate_claim(claim, evidence, rule, mismatch_res, attempt=2)
        assert r2.status == "RETRY_NEEDED"

        # Attempt 3 (limit) -> UNRESOLVED
        r3 = validator.validate_claim(claim, evidence, rule, mismatch_res, attempt=3)
        assert r3.status == "UNRESOLVED"
        assert "Maximum of 3 validation attempts reached" in r3.feedback_message
    finally:
        engine.close()


def test_reviewer_note_targeted_reinvestigation(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    excel_path = input_dir / "safety.xlsx"
    create_sample_workbook(excel_path, rows_count=30)

    manifest = [{
        "role": "source",
        "filename": "safety.xlsx",
        "stored_name": "safety.xlsx",
        "size": excel_path.stat().st_size,
    }]
    outline = [{"id": "sec-16.3.1.1", "section_number": "16.3.1.1", "title": "Cardiac failure"}]
    orch = MultiAgentOrchestrator("guidance-run", tmp_path, input_dir, manifest, outline)
    try:
        orch.run_autonomous_investigation()
        # Add user guidance note
        orch.add_user_note("sec-16.3.1.1", "Ensure only Spontaneous cases are included.")

        mapping = orch.mappings["sec-16.3.1.1"]
        assert len(mapping.user_notes) == 1
        assert "Ensure only Spontaneous" in mapping.user_notes[0]
        # Re-investigation ran and produced artifacts
        matrix_file = orch.sandbox.read_file("complete_traceability_matrix.json")
        assert "Ensure only Spontaneous" in matrix_file
    finally:
        orch.data_engine.close()


def test_source_immutability_and_readonly_protection(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    source_file = input_dir / "protected.xlsx"
    source_file.write_text("protected content", encoding="utf-8")

    sandbox = AgentSandbox(tmp_path, input_dir)

    # Deleting source file through sandbox must be strictly forbidden
    with pytest.raises(PermissionError):
        sandbox.delete_file("protected.xlsx")

    # Source files on filesystem must have read-only attributes
    assert not (source_file.stat().st_mode & 0o200)


def test_ag_ui_event_replay():
    manager = AGUIEventManager()
    run_id = "replay-test-run"

    manager.emit(run_id, "agent1", "Agent One", "Role One", "explorer.file.started", "Started file 1")
    manager.emit(run_id, "agent2", "Agent Two", "Role Two", "rules.draft.created", "Drafted rule 1")

    # Client retrieves from start (replay)
    all_events = manager.get_events(run_id, since_idx=0)
    assert len(all_events) == 2
    assert all_events[0]["event_type"] == "explorer.file.started"
    assert all_events[1]["event_type"] == "rules.draft.created"

    # Client retrieves incremental
    incremental = manager.get_events(run_id, since_idx=1)
    assert len(incremental) == 1
    assert incremental[0]["event_type"] == "rules.draft.created"


def test_multi_turn_bedrock_converse_tool_loop(monkeypatch):
    """Verifies that converse_with_tools handles multi-turn tool calling and returns final result."""
    turns_called = 0

    class MockBedrockClient:
        def converse(self, **kwargs):
            nonlocal turns_called
            turns_called += 1
            if turns_called == 1:
                # Turn 1: Sonnet emits toolUse
                return {
                    "output": {
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "toolUse": {
                                        "toolUseId": "call_123",
                                        "name": "search_data",
                                        "input": {"term": "cardiac"},
                                    }
                                }
                            ],
                        }
                    },
                    "stopReason": "tool_use",
                }
            else:
                # Turn 2: Sonnet receives toolResult and gives final text
                return {
                    "output": {
                        "message": {
                            "role": "assistant",
                            "content": [{"text": "Found 1 matching cardiac case."}],
                        }
                    },
                    "stopReason": "end_turn",
                }

    from app.services import bedrock
    monkeypatch.setattr(bedrock, "get_bedrock_client", lambda: MockBedrockClient())

    executed_tools = []
    def fake_executor(name, inp):
        executed_tools.append((name, inp))
        return {"matching_cases": 1}

    res = converse_with_tools(
        initial_prompt="Analyze cardiac data",
        tools=[{"name": "search_data", "description": "search", "inputSchema": {"json": {}}}],
        tool_executor=fake_executor,
    )

    assert res["success"] is True
    assert turns_called == 2
    assert len(executed_tools) == 1
    assert executed_tools[0][0] == "search_data"
    assert "Found 1 matching cardiac case" in res["text"]

