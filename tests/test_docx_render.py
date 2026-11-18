from hashlib import sha256
from pathlib import Path
from docx import Document
from app.services.docx_template import extract_section_tables, consolidate_template
from app.services.docx_render import render_report


def build_doc(path: Path):
    doc = Document()
    doc.add_heading("Evaluation of risks and new information", level=1)
    doc.add_heading("Example risk", level=3)
    table = doc.add_table(rows=7, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 0).text = "Post-marketing data – number of initial cases in the reporting interval (per topic/total): 8/200"
    labels = ["Search criteria:", "Spontaneous:", "Report from other studies:", "Evaluation:", "Conclusion:", "Data source:"]
    values = ["MedDRA PTs PT Alpha", "7 cases", "1 case", "Previous evaluation", "Previous conclusion", "Data source: prior tables"]
    for i, (label, value) in enumerate(zip(labels, values), 1):
        table.cell(i, 0).text = label; table.cell(i, 1).text = value
    doc.add_heading("Important identified risks", level=2)
    doc.add_paragraph("This paragraph is outside the target tables and must remain unchanged.")
    doc.save(path)


def test_render_updates_only_section_table_and_preserves_source(tmp_path):
    source = tmp_path / "base.docx"; output = tmp_path / "generated.docx"
    build_doc(source)
    before = sha256(source.read_bytes()).hexdigest()
    profile = extract_section_tables(source)
    schema, _ = consolidate_template([profile], "Example template", "tenant")
    schema["base_tables"] = schema["tables"]
    topic = schema["tables"][0]
    metrics = [{"table_id": topic["table_id"], "status": "calculated_candidate", "numerator": 2,
                "denominator": 20, "source_breakdown_complete": True,
                "source_breakdown": [{"classification": "Spontaneous", "count": 1},
                                     {"classification": "Report from other studies", "count": 1}]}]
    result = render_report(source, schema, metrics, output,
                           narratives={topic["table_id"]:{"evaluation":"New evaluation", "conclusion":"New conclusion"}},
                           source_files=["events.xlsx"])
    assert output.exists()
    assert sha256(source.read_bytes()).hexdigest() == before
    generated = Document(output)
    table = generated.tables[0]
    assert "2/20" in table.cell(0,0).text
    assert "1 case" in table.cell(2,1).text
    assert "1 case" in table.cell(3,1).text
    assert "New evaluation" in table.cell(4,1).text
    assert "New conclusion" in table.cell(5,1).text
    assert "events.xlsx" in table.cell(6,1).text
    assert "outside the target tables" in generated.paragraphs[-1].text
    assert result["only_section_16_3_tables_targeted"] is True


def test_unmapped_topic_does_not_retain_previous_period_numbers(tmp_path):
    source = tmp_path / "base.docx"; output = tmp_path / "generated.docx"
    build_doc(source)
    profile = extract_section_tables(source)
    schema, _ = consolidate_template([profile], "Example template", "tenant")
    schema["base_tables"] = schema["tables"]
    topic = schema["tables"][0]
    metrics = [{"table_id": topic["table_id"], "status": "mapping_incomplete", "reason": "Missing date map"}]
    render_report(source, schema, metrics, output)
    table = Document(output).tables[0]
    assert "REVIEW REQUIRED" in table.cell(0,0).text
    assert "REVIEW REQUIRED" in table.cell(2,1).text
    assert "REVIEW REQUIRED" in table.cell(3,1).text
    assert "8/200" not in table.cell(0,0).text
