from __future__ import annotations

from app.runtime.source_compatibility import compare_to_blueprint


def blueprint():
    return {
        "blueprint_id": "bp_a", "version": 2,
        "datasets": [{
            "dataset_id": "case_dataset", "source_candidates": ["old_export.xlsx"],
            "sheet_candidates": ["Cases"],
            "fields": [
                {"logical_name": "case_id", "physical_name": "Case Number", "aliases": [], "required": True, "mapping_state": "observed"},
                {"logical_name": "receipt_date", "physical_name": "Receipt Date", "aliases": [], "required": True, "mapping_state": "observed"},
            ],
        }],
    }


def test_exact_logical_fields_allow_renamed_source_file():
    report = compare_to_blueprint(
        generation_id="gen1", blueprint=blueprint(), source_manifest_hash="a" * 64,
        profiles=[{"file_name": "new_export_2026.xlsx", "sheet_name": "SafetyData", "header_row_index": 2,
                   "columns": ["Case Number", "Receipt Date", "Extra"], "row_count": 20}],
    )
    assert report.status == "compatible"
    assert any(x.get("observed_physical_field") == "Case Number" for x in report.mappings)


def test_alias_mapping_requires_human_review():
    bp = blueprint()
    bp["datasets"][0]["fields"][0]["aliases"] = ["Case ID"]
    report = compare_to_blueprint(
        generation_id="gen2", blueprint=bp, source_manifest_hash="b" * 64,
        profiles=[{"file_name": "new.csv", "sheet_name": None, "header_row_index": 0,
                   "columns": ["Case ID", "Receipt Date"], "row_count": 5}],
    )
    assert report.status == "compatible_with_warnings"
    assert any(x.code == "FIELD_MAPPING_REQUIRES_REVIEW" for x in report.drift)


def test_missing_field_contract_blocks_generation():
    bp = blueprint()
    bp["datasets"][0]["fields"] = []
    report = compare_to_blueprint(
        generation_id="gen3", blueprint=bp, source_manifest_hash="c" * 64,
        profiles=[{"file_name": "same.xlsx", "sheet_name": "Cases", "header_row_index": 0,
                   "columns": ["Case Number"], "row_count": 1}],
    )
    assert report.status == "blocked"
    assert report.drift[0].code == "FIELD_CONTRACT_MISSING"
