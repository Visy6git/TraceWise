from pathlib import Path
from openpyxl import Workbook
from app.services.excel_profile import profile_xlsx
from app.services.mapper import heuristic_mapping, calculate_topic_metrics


def make_event_file(path: Path):
    wb = Workbook(); ws = wb.active; ws.title = "Events"
    ws.append(["Export header", "not data"])
    ws.append(["Case Number", "Event PT", "Primary Source", "Initial Follow-up Flag", "Initial Approval Date"])
    ws.append(["C1", "PT Alpha", "Spontaneous", "Initial", "20250101"])
    ws.append(["C1", "PT Alpha", "Spontaneous", "Initial", "20250101"])
    ws.append(["C2", "PT Beta", "Report from other studies", "Initial", "20250102"])
    ws.append(["C3", "PT Alpha", "Spontaneous", "Follow-up", "20250103"])
    ws.append(["C4", "PT Alpha", "Spontaneous", "Initial", "20240101"])
    ws.append(["C5", "PT Alpha", "Spontaneous", "Non-initial", "20250104"])
    wb.save(path)


def _mapping_from_profile(path: Path):
    profile = profile_xlsx(path)
    result = heuristic_mapping([profile])
    # For the fixture's explicit headers, all core roles should be identified.
    assert result["mapping"]["case_id"]
    assert result["mapping"]["event_term"]
    assert result["mapping"]["source_category"]
    assert result["mapping"]["initial_flag"]
    assert result["mapping"]["approval_date"]
    return result["mapping"]


def test_calculates_distinct_cases_and_event_rows_with_explicit_period_initial_filters(tmp_path):
    p = tmp_path / "events.xlsx"; make_event_file(p)
    mapping = _mapping_from_profile(p)
    topic = {"table_id": "t1", "topic_heading": "Example risk", "criterion_type": "MedDRA PTs",
             "criterion_terms": ["PT Alpha", "PT Beta"], "requires_initial_only": True,
             "requires_reporting_interval": True}
    distinct = calculate_topic_metrics(topic, mapping, tmp_path, "2025-01-01", "2025-12-31", "distinct_case")
    assert distinct["status"] == "calculated_candidate"
    assert distinct["numerator"] == 2
    assert distinct["denominator"] == 2
    assert distinct["source_breakdown_complete"] is True
    assert sum(x["count"] for x in distinct["source_breakdown"]) == 2
    assert distinct["evidence"][0]["excel_row"] == 3

    events = calculate_topic_metrics(topic, mapping, tmp_path, "2025-01-01", "2025-12-31", "event_rows")
    assert events["numerator"] == 3
    assert events["denominator"] == 3


def test_interval_template_blocks_calculation_without_date_mapping(tmp_path):
    p = tmp_path / "events.xlsx"; make_event_file(p)
    mapping = _mapping_from_profile(p)
    mapping["approval_date"] = None
    topic = {"table_id": "t1", "topic_heading": "Example risk", "criterion_type": "MedDRA PTs",
             "criterion_terms": ["PT Alpha"], "requires_initial_only": True,
             "requires_reporting_interval": True}
    result = calculate_topic_metrics(topic, mapping, tmp_path, "2025-01-01", "2025-12-31")
    assert result["status"] == "mapping_incomplete"
    assert "date column" in result["reason"].lower()


def test_separate_denominator_source_is_supported(tmp_path):
    event_path = tmp_path / "events.xlsx"; make_event_file(event_path)
    denominator_path = tmp_path / "case_summary.xlsx"
    wb = Workbook(); ws = wb.active; ws.title = "Case Cohort"
    ws.append(["Case Number", "Initial Follow-up Flag", "Approval Date"])
    ws.append(["C1", "Initial", "20250101"])
    ws.append(["C2", "Initial", "20250102"])
    ws.append(["C3", "Initial", "20250103"])
    ws.append(["C4", "Initial", "20240101"])
    wb.save(denominator_path)

    mapping = _mapping_from_profile(event_path)
    denominator_profile = profile_xlsx(denominator_path)
    denominator_map = heuristic_mapping([denominator_profile])["mapping"]
    mapping["denominator_case_id"] = denominator_map["case_id"]
    mapping["denominator_initial_flag"] = denominator_map["initial_flag"]
    mapping["denominator_approval_date"] = denominator_map["approval_date"]
    topic = {"table_id": "t1", "topic_heading": "Example risk", "criterion_type": "MedDRA PTs",
             "criterion_terms": ["PT Alpha", "PT Beta"], "requires_initial_only": True,
             "requires_reporting_interval": True}
    result = calculate_topic_metrics(topic, mapping, tmp_path, "2025-01-01", "2025-12-31", "distinct_case")
    assert result["status"] == "calculated_candidate"
    assert result["numerator"] == 2
    assert result["denominator"] == 3
    assert result["denominator_source"] == "separate_denominator_worksheet"


def test_date_and_initial_maps_must_belong_to_same_source_sheet(tmp_path):
    p = tmp_path / "events.xlsx"; make_event_file(p)
    mapping = _mapping_from_profile(p)
    mapping["approval_date"] = {**mapping["approval_date"], "source_file": "different.xlsx"}
    topic = {"table_id": "t1", "topic_heading": "Example risk", "criterion_type": "MedDRA PTs",
             "criterion_terms": ["PT Alpha"], "requires_initial_only": True,
             "requires_reporting_interval": True}
    result = calculate_topic_metrics(topic, mapping, tmp_path, "2025-01-01", "2025-12-31")
    assert result["status"] == "mapping_incomplete"
    assert "date" in result["reason"].lower()
