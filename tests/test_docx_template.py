from pathlib import Path
from docx import Document
from app.services.docx_template import extract_section_tables, consolidate_template


def build_reference_docx(path: Path):
    doc = Document()
    doc.add_heading("A different section", level=1)
    outside = doc.add_table(rows=2, cols=2)
    outside.cell(0, 0).text = "Post-marketing data"
    outside.cell(0, 1).text = "should not be considered"
    doc.add_heading("Evaluation of risks and new information", level=1)
    doc.add_paragraph("Data in this PBRER Section are presented on event level.")
    doc.add_heading("Impulse control disorders", level=3)
    table = doc.add_table(rows=7, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 0).text = "Post-marketing data – number of initial cases in the reporting interval (per topic/total): 2/100"
    labels = ["Search criteria:", "Spontaneous:", "Report from other studies:", "Evaluation:", "Conclusion:", "Data source:"]
    values = ["MedDRA PTs PT Alpha; PT Beta", "1 case", "1 case", "Old evaluation", "Old conclusion", "Data source: old tables"]
    for i, (label, value) in enumerate(zip(labels, values), start=1):
        table.cell(i, 0).text = label
        table.cell(i, 1).text = value
    # Continuation table: narrative-only continuation must attach to the preceding topic.
    continuation = doc.add_table(rows=3, cols=2)
    continuation.cell(0, 0).text = "Evaluation (cont'd):"
    continuation.cell(0, 1).text = "Continued evaluation"
    continuation.cell(1, 0).text = "Conclusion:"
    continuation.cell(1, 1).text = "Continued conclusion"
    continuation.cell(2, 0).text = "Data source:"
    continuation.cell(2, 1).text = "Data source: continuation"
    doc.add_heading("Important identified risks", level=2)
    after = doc.add_table(rows=2, cols=2)
    after.cell(0, 0).text = "Post-marketing data"
    after.cell(0, 1).text = "outside Section 16.3"
    doc.save(path)


def test_extracts_only_section_16_3_tables_and_normalizes_fields(tmp_path):
    path = tmp_path / "reference.docx"
    build_reference_docx(path)
    profile = extract_section_tables(path)
    assert profile["section_16_3_found"] is True
    assert len(profile["tables"]) == 2
    first = profile["tables"][0]
    assert first["docx_table_index"] == 1
    assert first["criterion_type"] == "MedDRA PTs"
    assert first["criterion_terms"] == ["PT Alpha", "PT Beta"]
    assert first["requires_initial_only"] is True
    assert first["requires_reporting_interval"] is True
    assert {f["key"] for f in first["fields"]} >= {
        "topic_total", "search_criteria", "source_spontaneous", "source_other_studies",
        "evaluation", "conclusion", "data_source"
    }


def test_consolidation_marks_continuation_table_and_builds_master_md(tmp_path):
    path = tmp_path / "reference.docx"
    build_reference_docx(path)
    profile = extract_section_tables(path)
    schema, master = consolidate_template([profile], "Client PBRER 16.3", "tenant-x")
    assert schema["reporting_interval_required"] is True
    assert schema["tables"][1]["continuation_of_previous"] is True
    assert schema["tables"][1]["parent_topic_table_id"] == schema["tables"][0]["table_id"]
    assert "event level" in master.lower()
    assert "PT and HLT/SMQ" in master or "HLT" in master
    assert "never" in master.lower() or "Do not" in master
