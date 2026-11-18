from pathlib import Path
from docx import Document
import app.services.template_agent as ta
from app.services.llm_client import (
    normalize_lmstudio_base_url,
    _strip_reasoning_and_extract_json,
    _parse_xml_tool_call,
    _extract_tool_arguments,
)


def _build_multi_topic_docx(path: Path):
    doc = Document()
    doc.add_heading("16.1 Summary of Safety Concerns", level=1)
    # Plain body text mention before Section 16.3 must NOT trigger Section 16.3 early!
    doc.add_paragraph("Evaluation of risks and new information")
    outside = doc.add_table(rows=2, cols=2)
    outside.cell(0, 0).text = "Outside table"
    outside.cell(0, 1).text = "Ignore me"

    doc.add_heading("16.3 Evaluation of risks and new information", level=1)
    doc.add_paragraph("Data in Section 16.3 are presented on event level.")

    # Topic 1 with a page-break continuation table
    doc.add_heading("Topic Alpha", level=3)
    t1 = doc.add_table(rows=4, cols=2)
    t1.cell(0, 0).merge(t1.cell(0, 1))
    t1.cell(0, 0).text = "Post-marketing data – initial cases (topic/total): 5/100"
    t1.cell(1, 0).text = "Search criteria:"
    t1.cell(1, 1).text = "MedDRA PTs Alpha One; Alpha Two"
    t1.cell(2, 0).text = "Spontaneous:"
    t1.cell(2, 1).text = "3 cases"
    t1.cell(3, 0).text = "Evaluation:"
    t1.cell(3, 1).text = "Part 1 of evaluation"

    t1_cont = doc.add_table(rows=2, cols=2)
    t1_cont.cell(0, 0).text = "Evaluation (cont'd):"
    t1_cont.cell(0, 1).text = "Part 2 of evaluation"
    t1_cont.cell(1, 0).text = "Conclusion:"
    t1_cont.cell(1, 1).text = "No change to RSI."

    # Topic 2
    doc.add_heading("Topic Beta", level=3)
    t2 = doc.add_table(rows=3, cols=2)
    t2.cell(0, 0).merge(t2.cell(0, 1))
    t2.cell(0, 0).text = "Post-marketing data – initial cases (topic/total): 2/100"
    t2.cell(1, 0).text = "Search criteria:"
    t2.cell(1, 1).text = "MedDRA SMQ Beta Narrow"
    t2.cell(2, 0).text = "Conclusion:"
    t2.cell(2, 1).text = "Continue routine PV."

    doc.add_heading("16.4 Characterisation of risks", level=1)
    after = doc.add_table(rows=2, cols=2)
    after.cell(0, 0).text = "After 16.3"
    after.cell(0, 1).text = "Ignore me too"
    doc.save(path)


def test_raw_section_16_3_reader_ignores_body_mentions_and_merges_continuation(tmp_path):
    doc_path = tmp_path / "client_pbrer.docx"
    _build_multi_topic_docx(doc_path)

    profile = ta.extract_raw_section_16_3(doc_path)
    assert profile["section_16_3_found"] is True
    assert len(profile["tables"]) == 2
    assert profile["tables"][0]["topic_heading"] == "Topic Alpha"
    assert profile["tables"][0]["row_count"] == 6
    assert len(profile["tables"][0]["merged_docx_indices"]) == 2
    assert profile["tables"][1]["topic_heading"] == "Topic Beta"
    assert profile["tables"][1]["row_count"] == 3


def test_agui_table_by_table_strands_tool_pipeline(tmp_path, monkeypatch):
    doc_path = tmp_path / "client_pbrer.docx"
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _build_multi_topic_docx(doc_path)

    tool_calls_seen = []

    def fake_invoke_tool_call(system_prompt, user_prompt, tool_name, tool_description, input_model, **kwargs):
        tool_calls_seen.append((tool_name, user_prompt))
        if tool_name == "register_table_blueprint":
            if "client_pbrer-table-1" in user_prompt:
                return ta.BlueprintTableSpec(
                    table_id="client_pbrer-table-1",
                    topic_heading="Topic Alpha",
                    criterion_type="MedDRA PTs",
                    criterion_terms=["Alpha One", "Alpha Two"],
                    requires_reporting_interval=True,
                    requires_initial_only=True,
                    fields=[
                        ta.BlueprintFieldSpec(
                            field_label="Initial cases (topic/total)",
                            key="topic_total",
                            type="count_ratio",
                            generic_placeholder="{{topic_cases}} / {{total_cases}}",
                            source_intent="Topic count over total reporting interval count",
                            required=True,
                            row_index=0,
                            cell_index=0,
                        ),
                        ta.BlueprintFieldSpec(
                            field_label="Search criteria",
                            key="search_criteria",
                            type="criteria",
                            generic_placeholder="{{search_criteria}}",
                            source_intent="MedDRA terms defining this safety topic",
                            required=True,
                            row_index=1,
                            cell_index=1,
                        ),
                        ta.BlueprintFieldSpec(
                            field_label="Conclusion",
                            key="conclusion",
                            type="narrative",
                            generic_placeholder="{{conclusion_narrative}}",
                            source_intent="Reviewer-authored interval conclusion",
                            required=True,
                            row_index=5,
                            cell_index=1,
                        ),
                    ],
                )
            return ta.BlueprintTableSpec(
                table_id="client_pbrer-table-3",
                topic_heading="Topic Beta",
                criterion_type="MedDRA SMQ",
                criterion_terms=["Beta Narrow"],
                requires_reporting_interval=True,
                requires_initial_only=True,
                fields=[
                    ta.BlueprintFieldSpec(
                        field_label="Initial cases (topic/total)",
                        key="topic_total",
                        type="count_ratio",
                        generic_placeholder="{{topic_cases}} / {{total_cases}}",
                        source_intent="Topic count over total reporting interval count",
                        required=True,
                        row_index=0,
                        cell_index=0,
                    ),
                    ta.BlueprintFieldSpec(
                        field_label="Conclusion",
                        key="conclusion",
                        type="narrative",
                        generic_placeholder="{{conclusion_narrative}}",
                        source_intent="Reviewer-authored interval conclusion",
                        required=True,
                        row_index=2,
                        cell_index=1,
                    ),
                ],
            )
        if tool_name == "publish_master_knowledge":
            return ta.MasterMarkdownResponse(
                master_md="# Client Section 16.3 Master Guide\n\nObserved conventions across 2 tables.",
                reference_summaries=[
                    ta.ReferenceTableSummary(
                        table_id="client_pbrer-table-1",
                        topic_heading="Topic Alpha",
                        why_selected="Full multi-row topic table spanning continuation pages.",
                        structure_summary="6 rows with count ratio header, PT list, spontaneous count, and conclusion.",
                        example_fields=["Initial cases -> {{topic_cases}} / {{total_cases}}"],
                    ),
                    ta.ReferenceTableSummary(
                        table_id="client_pbrer-table-3",
                        topic_heading="Topic Beta",
                        why_selected="Compact SMQ-based topic table variant.",
                        structure_summary="3 rows with SMQ search criteria and conclusion.",
                        example_fields=["Conclusion -> {{conclusion_narrative}}"],
                    ),
                ],
            )
        raise AssertionError(f"Unexpected tool_name: {tool_name}")

    monkeypatch.setattr(ta, "invoke_tool_call", fake_invoke_tool_call)
    monkeypatch.setattr(
        ta,
        "llm_status_info",
        lambda: {"llm_enabled": True, "llm_provider": "lmstudio", "llm_model_id": "prism-ml/bonsai-27b"},
    )

    events = []
    out = ta.run_agui_template_pipeline(
        run_id="run_1",
        tenant_id="tenant-acme",
        run_name="Acme 16.3",
        docx_paths=[doc_path],
        work_dir=work_dir,
        emitter=lambda et, payload: events.append((et, payload)),
    )

    schema = out["schema"]
    # 1. Called register_table_blueprint once PER table (table-by-table) + publish_master_knowledge
    assert [name for name, _ in tool_calls_seen] == [
        "register_table_blueprint",
        "register_table_blueprint",
        "publish_master_knowledge",
    ]
    assert len(schema["base_tables"]) == 2
    assert schema["generation_mode"] == "llm_strands_tool_table_by_table"

    # 2. Immediate table-by-table AG-UI events emitted as each table finished
    table_ready_events = [p["value"] for et, p in events if et == "CUSTOM" and p.get("name") == "blueprint.table_ready"]
    assert len(table_ready_events) == 2
    assert table_ready_events[0]["completed"] == 1 and table_ready_events[0]["total"] == 2
    assert table_ready_events[1]["completed"] == 2 and table_ready_events[1]["total"] == 2

    # Continuation field locator resolves to physical table index 2 (t1_cont), row 1
    alpha_conclusion = next(f for f in schema["base_tables"][0]["fields"] if f["key"] == "conclusion")
    assert alpha_conclusion["locator"]["docx_table_index"] == 2
    assert alpha_conclusion["locator"]["row"] == 1

    # 3. Detected table fields deterministically derived from LLM blueprint
    by_key = {f["key"]: f for f in schema["common_fields"]}
    assert by_key["topic_total"]["occurrences"] == 2
    assert by_key["conclusion"]["occurrences"] == 2
    assert by_key["search_criteria"]["occurrences"] == 1

    # 4. master.md generated with 2 best reference summaries
    assert len(schema["reference_summaries"]) == 2
    assert "## Best Reference Table Summaries" in out["master_md"]

    # 5. Temporary highlight on reference_documents turned on then off
    highlights = [
        (p["value"]["target"], p["value"]["active"])
        for et, p in events
        if et == "CUSTOM" and p.get("name") == "ui.highlight"
    ]
    assert ("reference_documents", True) in highlights
    assert ("reference_documents", False) in highlights
    assert highlights.index(("reference_documents", True)) < highlights.index(("reference_documents", False))


def test_lmstudio_xml_and_json_tool_call_parsers():
    assert normalize_lmstudio_base_url("http://127.0.0.1:1234") == "http://127.0.0.1:1234/v1"
    assert _strip_reasoning_and_extract_json("<think>hmm</think>\n```json\n{\"ok\": true}\n```") == {"ok": True}

    xml_sample = (
        "<tool_call>\n"
        "<function=register_table_blueprint>\n"
        "<parameter=table_id>\nt1\n</parameter>\n"
        "<parameter=topic_heading>\nSleep attacks\n</parameter>\n"
        "<parameter=requires_initial_only>\ntrue\n</parameter>\n"
        "<parameter=fields>\n[{\"field_label\":\"Cases\",\"key\":\"cases\",\"type\":\"count\","
        "\"generic_placeholder\":\"{{cases}}\",\"source_intent\":\"Count\"}]\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    parsed = _parse_xml_tool_call(xml_sample, "register_table_blueprint")
    assert parsed["table_id"] == "t1"
    assert parsed["requires_initial_only"] is True
    assert len(parsed["fields"]) == 1

    args = _extract_tool_arguments({"content": "", "reasoning_content": xml_sample, "tool_calls": []}, "register_table_blueprint")
    assert args["topic_heading"] == "Sleep attacks"


def test_deduplication_and_placeholder_sanitization():
    raw = {
        "table_id": "doc-table-36",
        "source_file": "doc.docx",
        "docx_table_index": 36,
        "merged_docx_indices": [36],
        "topic_heading": "Dystonia",
        "table_style": "Table Grid",
        "column_count": 2,
        "row_count": 3,
        "raw_rows": [
            {"row_index": 0, "physical_docx_table_index": 36, "physical_row_index": 0,
             "cells": [{"cell_index": 0, "grid_span": 2, "paragraphs": ["Post-marketing data: 3/3651"], "text": "Post-marketing data: 3/3651"}]},
            {"row_index": 1, "physical_docx_table_index": 36, "physical_row_index": 1,
             "cells": [{"cell_index": 0, "grid_span": 1, "paragraphs": ["Search criteria:"], "text": "Search criteria:"},
                       {"cell_index": 1, "grid_span": 1, "paragraphs": ["Narrow SMQ 'Dystonia'"], "text": "Narrow SMQ 'Dystonia'"}]},
            {"row_index": 2, "physical_docx_table_index": 36, "physical_row_index": 2,
             "cells": [{"cell_index": 0, "grid_span": 2, "paragraphs": ["Data source: data on file, Tables 16, 376"], "text": "Data source: data on file, Tables 16, 376"}]},
        ],
    }
    spec = {
        "table_id": "doc-table-36",
        "topic_heading": "Dystonia",
        "fields": [
            {"field_label": "Post-marketing data: 3/3651", "key": "topic_total", "type": "count", "generic_placeholder": "{{...}}", "source_intent": "Initial cases", "row_index": 0, "cell_index": 0},
            {"field_label": "Search criteria:", "key": "search_criteria", "type": "text", "generic_placeholder": "{{...}}", "source_intent": "MedDRA terms", "row_index": 1, "cell_index": 0},
            {"field_label": "Narrow SMQ 'Dystonia'", "key": "search_criteria", "type": "text", "generic_placeholder": "{{...}}", "source_intent": "MedDRA terms", "row_index": 1, "cell_index": 1},
            {"field_label": "Data source: data on file, Tables 16, 376", "key": "data_source", "type": "text", "generic_placeholder": "{{...}}", "source_intent": "Reference tables", "row_index": 2, "cell_index": 0},
        ],
    }
    assembled = ta._assemble_blueprint_table(raw, spec)
    assert len(assembled["fields"]) == 3
    by_key = {f["key"]: f for f in assembled["fields"]}
    assert by_key["topic_total"]["label"] == "Post-marketing data"
    assert by_key["topic_total"]["placeholder"] == "{{topic_total}}"
    assert by_key["search_criteria"]["label"] == "Search criteria"
    assert by_key["search_criteria"]["locator"]["cell"] == 1
    assert by_key["search_criteria"]["placeholder"] == "{{search_criteria}}"
    assert by_key["data_source"]["label"] == "Data source"
    assert "DO NOT COPY" in ta.SINGLE_TABLE_TOOL_SYSTEM_PROMPT


def test_product_template_uses_dedicated_prompts_and_carries_forward_titles_and_meddra(tmp_path, monkeypatch):
    doc_path = tmp_path / "sifrol_product.docx"
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    exact_title = (
        "Impulse control disorders such as compulsive shopping, pathological gambling, "
        "hypersexuality, binge eating and other impulse control behaviour"
    )
    meddra_criteria = (
        "MedDRA PTs: Abnormal behaviour; Behaviour disorder; Binge eating; Compulsions; "
        "Compulsive shopping; Gambling disorder; Hypersexuality; Impulse-control disorder"
    )

    doc = Document()
    doc.add_heading("16.3 Evaluation of risks and new information", level=1)
    doc.add_heading(exact_title, level=3)
    t1 = doc.add_table(rows=4, cols=2)
    t1.cell(0, 0).merge(t1.cell(0, 1))
    t1.cell(0, 0).text = "Post-marketing data – initial cases (topic/total): 12/3651"
    t1.cell(1, 0).text = "Search criteria:"
    t1.cell(1, 1).text = meddra_criteria
    t1.cell(2, 0).text = "Spontaneous:"
    t1.cell(2, 1).text = "10 cases"
    t1.cell(3, 0).text = "Conclusion:"
    t1.cell(3, 1).text = "Prior period conclusion text."
    doc.save(doc_path)

    captured_prompts = []

    def fake_invoke_tool_call(system_prompt, user_prompt, tool_name, tool_description, input_model, **kwargs):
        captured_prompts.append((tool_name, system_prompt, user_prompt))
        if tool_name == "register_table_blueprint":
            return ta.BlueprintTableSpec(
                table_id="sifrol_product-table-0",
                # Deliberately shortened by LLM — product pipeline must still preserve exact DOCX title!
                topic_heading="Impulse control disorders",
                criterion_type="MedDRA PTs",
                criterion_terms=[
                    "Abnormal behaviour",
                    "Binge eating",
                    "Compulsive shopping",
                    "Gambling disorder",
                    "Hypersexuality",
                ],
                requires_reporting_interval=True,
                requires_initial_only=True,
                fields=[
                    ta.BlueprintFieldSpec(
                        field_label="Post-marketing data – initial cases (topic/total)",
                        key="topic_total",
                        type="count_ratio",
                        generic_placeholder="{{topic_initial_cases}} / {{total_initial_cases}}",
                        source_intent="Initial cases for topic over total initial cases",
                        required=True,
                        row_index=0,
                        cell_index=0,
                    ),
                    ta.BlueprintFieldSpec(
                        field_label="Search criteria",
                        key="search_criteria",
                        type="criteria",
                        # Even if LLM emits generic placeholder, guardrail carries forward verbatim DOCX MedDRA terms
                        generic_placeholder="{{search_criteria}}",
                        source_intent="Carried-forward MedDRA PTs for impulse control disorders",
                        required=True,
                        row_index=1,
                        cell_index=1,
                    ),
                    ta.BlueprintFieldSpec(
                        field_label="Spontaneous",
                        key="source_spontaneous",
                        type="count",
                        generic_placeholder="{{spontaneous_case_count}}",
                        source_intent="Spontaneous case count",
                        required=True,
                        row_index=2,
                        cell_index=1,
                    ),
                    ta.BlueprintFieldSpec(
                        field_label="Conclusion",
                        key="conclusion",
                        type="narrative",
                        generic_placeholder="{{conclusion_narrative}}",
                        source_intent="Reviewer conclusion for current period",
                        required=True,
                        row_index=3,
                        cell_index=1,
                    ),
                ],
            )
        if tool_name == "publish_master_knowledge":
            return ta.MasterMarkdownResponse(
                master_md="# Product Template Master Guide\n\nCarries forward MedDRA PTs verbatim.",
                reference_summaries=[
                    ta.ReferenceTableSummary(
                        table_id="sifrol_product-table-0",
                        topic_heading=exact_title,
                        why_selected="Primary product safety concern with fixed MedDRA PTs.",
                        structure_summary="4 rows with fixed MedDRA PTs and dynamic interval counts.",
                        example_fields=["Search criteria -> carried forward MedDRA PTs"],
                    )
                ],
            )
        raise AssertionError(f"Unexpected tool_name: {tool_name}")

    monkeypatch.setattr(ta, "invoke_tool_call", fake_invoke_tool_call)
    monkeypatch.setattr(
        ta,
        "llm_status_info",
        lambda: {"llm_enabled": True, "llm_provider": "lmstudio", "llm_model_id": "prism-ml/bonsai-27b"},
    )

    out = ta.run_agui_template_pipeline(
        run_id="run_product_1",
        tenant_id="tenant-sifrol",
        run_name="Sifrol Product 16.3",
        docx_paths=[doc_path],
        work_dir=work_dir,
        template_type="product",
    )

    # 1. Dedicated Product Template system prompts were used (different from generic prompts)
    assert ta.PRODUCT_TABLE_TOOL_SYSTEM_PROMPT != ta.SINGLE_TABLE_TOOL_SYSTEM_PROMPT
    assert ta.PRODUCT_MASTER_MD_TOOL_SYSTEM_PROMPT != ta.MASTER_MD_TOOL_SYSTEM_PROMPT
    assert captured_prompts[0][1] == ta.PRODUCT_TABLE_TOOL_SYSTEM_PROMPT
    assert captured_prompts[1][1] == ta.PRODUCT_MASTER_MD_TOOL_SYSTEM_PROMPT

    schema = out["schema"]
    assert schema["template_type"] == "product"
    assert schema["review_policy"]["carry_forward_topic_titles"] is True
    assert schema["review_policy"]["carry_forward_search_criteria"] is True

    # 2. Exact topic title and full MedDRA search criteria carried forward verbatim
    tbl = schema["base_tables"][0]
    assert tbl["template_type"] == "product"
    assert tbl["topic_title_carried_forward"] is True
    assert tbl["topic_heading"] == exact_title

    fields_by_key = {f["key"]: f for f in tbl["fields"]}
    assert fields_by_key["search_criteria"]["carried_forward"] is True
    assert fields_by_key["search_criteria"]["placeholder"] == meddra_criteria
    assert "{{" not in fields_by_key["search_criteria"]["placeholder"]

    # 3. Prior-period numbers and narratives remain generic placeholders
    assert fields_by_key["topic_total"]["carried_forward"] is False
    assert "{{" in fields_by_key["topic_total"]["placeholder"]
    assert fields_by_key["source_spontaneous"]["carried_forward"] is False
    assert fields_by_key["conclusion"]["carried_forward"] is False
    assert "Prior period conclusion" not in fields_by_key["conclusion"]["placeholder"]

    # 4. Detected common_fields marks search_criteria as carried_forward
    common_by_key = {f["key"]: f for f in schema["common_fields"]}
    assert common_by_key["search_criteria"]["carried_forward"] is True
    assert common_by_key["topic_total"]["carried_forward"] is False


def test_api_template_runs_accepts_product_type_and_approves(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import time
    import app.main as main_mod

    # Isolate DB and workspace for this test
    monkeypatch.setattr(main_mod.settings, "workspace_root", tmp_path)
    monkeypatch.setattr(main_mod.settings, "database_path", tmp_path / "test.sqlite3")
    main_mod.db.init_db()
    main_mod.RUNS.clear()

    def fake_run_template_learning(run_id, tenant_id, run_name, docx_paths, work_dir, progress, emitter=None, template_type="generic", *args, **kwargs):
        schema = {
            "template_version": "2.0",
            "template_name": run_name,
            "template_type": template_type,
            "tenant_id": tenant_id,
            "base_document": docx_paths[0].name,
            "base_tables": [
                {
                    "table_id": "t1",
                    "topic_heading": "Impulse control disorders",
                    "template_type": template_type,
                    "fields": [
                        {
                            "key": "search_criteria",
                            "label": "Search criteria",
                            "type": "criteria",
                            "placeholder": "MedDRA PTs: Gambling disorder" if template_type == "product" else "{{search_criteria}}",
                            "carried_forward": template_type == "product",
                        }
                    ],
                }
            ],
            "tables": [],
            "common_fields": [],
        }
        return {"schema": schema, "master_md": "# Master", "base_docx_path": docx_paths[0]}

    monkeypatch.setattr(main_mod, "run_template_learning", fake_run_template_learning)

    doc_path = tmp_path / "sample.docx"
    doc = Document()
    doc.add_heading("16.3 Evaluation of risks and new information", level=1)
    doc.save(doc_path)

    client = TestClient(main_mod.app)
    with open(doc_path, "rb") as fh:
        bad = client.post(
            "/api/template-runs",
            data={"tenant_id": "demo-tenant", "run_name": "Bad", "template_type": "invalid"},
            files=[("files", ("sample.docx", fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        )
    assert bad.status_code == 422

    with open(doc_path, "rb") as fh:
        res = client.post(
            "/api/template-runs",
            data={"tenant_id": "demo-tenant", "run_name": "Sifrol Product", "template_type": "product"},
            files=[("files", ("sample.docx", fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
        )
    assert res.status_code == 200
    body = res.json()
    assert body["template_type"] == "product"
    run_id = body["run_id"]

    # Wait briefly for background task
    for _ in range(40):
        status = client.get(f"/api/template-runs/{run_id}").json()
        if status["status"] == "completed":
            break
        time.sleep(0.05)
    assert status["status"] == "completed"
    tid = status["result"]["template_id"]

    listed = client.get("/api/templates", params={"tenant_id": "demo-tenant"}).json()["templates"]
    t_item = next(t for t in listed if t["template_id"] == tid)
    assert t_item["template_type"] == "product"

    approved = client.post(f"/api/templates/{tid}/approve", params={"tenant_id": "demo-tenant"}).json()
    assert approved["status"] == "approved"
    assert approved["template_type"] == "product"


