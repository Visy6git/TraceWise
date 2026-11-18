from pathlib import Path
from openpyxl import Workbook
from app.services.excel_profile import profile_xlsx, profile_to_markdown, build_master_summary


def test_profiles_workbook_headers_types_and_markdown(tmp_path):
    p = tmp_path / "cases.xlsx"
    wb = Workbook(); ws = wb.active; ws.title = "Safety Events"
    ws.append(["Report extract", "Client X"])
    ws.append(["Generated on", "2026-01-01"])
    ws.append(["Case Number", "Event PT (Primary Path)", "Derived-Primary-Source", "Initial Approval Date"])
    ws.append(["C-001", "Insomnia", "Spontaneous", "20250101"])
    ws.append(["C-002", "Hypertension", "Report from study-Other Studies", "20250102"])
    wb.save(p)

    profile = profile_xlsx(p)
    sheet = profile["sheets"][0]
    assert sheet["header_row"] == 3
    assert sheet["row_count"] == 2
    assert sheet["columns"][0]["semantic_role"] == "case_id"
    assert sheet["columns"][1]["semantic_role"] == "event_term"
    md = profile_to_markdown(profile)
    summary = build_master_summary([profile])
    assert "Safety Events" in md and "Inferred type" in md
    assert "cases.xlsx" in summary and "case identifier" in summary


def test_patient_identifier_is_not_automatically_treated_as_case_id(tmp_path):
    p = tmp_path / "patients.xlsx"
    wb = Workbook(); ws = wb.active
    ws.append(["Patient ID", "Event PT"])
    ws.append(["P-1", "Insomnia"])
    wb.save(p)
    profile = profile_xlsx(p)
    assert profile["sheets"][0]["columns"][0]["semantic_role"] is None
