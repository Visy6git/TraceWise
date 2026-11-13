"""Schema-only source profiler and conservative blueprint compatibility checker.

No row-level patient data is returned. Supports CSV/XLSX headers, counts, column
typing, unique cardinality, date semantics, hidden sheet detection and multiple-snapshot
profiling. A production implementation should use streaming Arrow/DuckDB.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.generation import GenerationCompatibilityReport, SchemaDriftItem


_DATE_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"),
    re.compile(r"^\d{2}/\d{2}/\d{4}$"),
    re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4}$"),
]


def _infer_type(value: str) -> str:
    v = value.strip()
    if not v:
        return "empty"
    if v.lower() in {"true", "false", "yes", "no"}:
        return "boolean"
    if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
        return "integer"
    try:
        float(v)
        return "float"
    except ValueError:
        pass
    for pat in _DATE_PATTERNS:
        if pat.match(v):
            return "date"
    return "string"


def _profile_sample_columns(header: list[str], data_sample: list[list[str]]) -> dict[str, dict[str, Any]]:
    col_profiles: dict[str, dict[str, Any]] = {}
    for col_idx, col_name in enumerate(header):
        if not col_name:
            continue
        values = [row[col_idx].strip() for row in data_sample if col_idx < len(row) and row[col_idx].strip()]
        unique_vals = set(values)
        types = {_infer_type(v) for v in values}
        inferred = "string"
        if types == {"integer"}:
            inferred = "integer"
        elif types in ({"integer", "float"}, {"float"}):
            inferred = "float"
        elif types == {"date"}:
            inferred = "date"
        elif types == {"boolean"}:
            inferred = "boolean"
        elif "date" in types and len(types) <= 2:
            inferred = "date"

        is_key = len(unique_vals) == len(values) and len(values) >= 2
        col_profiles[col_name] = {
            "inferred_type": inferred,
            "sample_count": len(values),
            "unique_sample_count": len(unique_vals),
            "is_candidate_key": is_key,
        }
    return col_profiles


def profile_source_headers(
    source_dir: Path,
    max_header_scan_rows: int = 30,
    sample_data_rows: int = 50,
) -> list[dict[str, Any]]:
    """Return candidate header rows, counts, column profiles, and metadata without retaining row data."""
    profiles: list[dict[str, Any]] = []
    for path in sorted(source_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".csv", ".xlsx"}:
            continue
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream)
                all_rows = list(reader)
            row_count = len(all_rows)
            for idx in range(min(max_header_scan_rows, row_count)):
                cols = [str(x).strip() for x in all_rows[idx]]
                nonempty = [x for x in cols if x]
                if len(nonempty) >= 2 and len(set(nonempty)) == len(nonempty):
                    sample_rows = [
                        [str(c) for c in r]
                        for r in all_rows[idx + 1 : idx + 1 + sample_data_rows]
                    ]
                    col_prof = _profile_sample_columns(cols, sample_rows)
                    snapshot_cols = [
                        c for c in cols
                        if any(k in c.lower() for k in ("snapshot", "as_of", "extract_date", "version"))
                    ]
                    multiple_snapshots = False
                    for sc in snapshot_cols:
                        if col_prof.get(sc, {}).get("unique_sample_count", 0) > 1:
                            multiple_snapshots = True
                            break

                    profiles.append({
                        "file_name": path.name,
                        "sheet_name": None,
                        "sheet_state": "visible",
                        "header_row_index": idx,
                        "columns": cols,
                        "column_profiles": col_prof,
                        "row_count": max(0, row_count - idx - 1),
                        "multiple_snapshots_detected": multiple_snapshots,
                    })
        else:
            try:
                from openpyxl import load_workbook
            except ImportError as exc:
                raise RuntimeError("openpyxl is required to profile XLSX sources") from exc
            wb = load_workbook(path, read_only=True, data_only=True)
            for ws in wb.worksheets:
                sheet_state = getattr(ws, "sheet_state", "visible") or "visible"
                all_rows: list[list[Any]] = []
                for r in ws.iter_rows(values_only=True):
                    all_rows.append(list(r))
                row_count = len(all_rows)
                for idx in range(min(max_header_scan_rows, row_count)):
                    cols = [str(x).strip() if x is not None else "" for x in all_rows[idx]]
                    nonempty = [x for x in cols if x]
                    if len(nonempty) >= 2 and len(set(nonempty)) == len(nonempty):
                        sample_rows = [
                            [str(c) if c is not None else "" for c in r]
                            for r in all_rows[idx + 1 : idx + 1 + sample_data_rows]
                        ]
                        col_prof = _profile_sample_columns(cols, sample_rows)
                        snapshot_cols = [
                            c for c in cols
                            if any(k in c.lower() for k in ("snapshot", "as_of", "extract_date", "version"))
                        ]
                        multiple_snapshots = False
                        for sc in snapshot_cols:
                            if col_prof.get(sc, {}).get("unique_sample_count", 0) > 1:
                                multiple_snapshots = True
                                break

                        profiles.append({
                            "file_name": path.name,
                            "sheet_name": ws.title,
                            "sheet_state": sheet_state,
                            "header_row_index": idx,
                            "columns": cols,
                            "column_profiles": col_prof,
                            "row_count": max(0, row_count - idx - 1),
                            "multiple_snapshots_detected": multiple_snapshots,
                        })
            wb.close()
    return profiles


def compare_to_blueprint(
    *,
    generation_id: str,
    blueprint: dict[str, Any],
    source_manifest_hash: str,
    profiles: list[dict[str, Any]],
) -> GenerationCompatibilityReport:
    """Match logical contracts to new physical files/sheets using schemas, not names.

    Exact prior file/sheet names are soft tie-breakers only. A dataset with no
    explicit logical field contract is blocked; the agent must not guess from a
    filename or a generic "case" keyword.
    """
    drift: list[SchemaDriftItem] = []
    mappings: list[dict[str, Any]] = []

    for dataset in blueprint.get("datasets", []):
        fields = dataset.get("fields") or []
        required_fields = [f for f in fields if f.get("required", True)]
        dataset_id = dataset.get("dataset_id", "unknown_dataset")

        if not fields:
            drift.append(SchemaDriftItem(
                code="FIELD_CONTRACT_MISSING",
                severity="blocking",
                dataset_id=dataset_id,
                expected="Logical fields + evidence-backed physical mappings",
                observed="No field contract in approved blueprint",
                suggested_action="Reopen Stage 3 learning and establish field contracts from approved Stage 1 profiles and Stage 2 evidence.",
            ))
            continue

        scored: list[tuple[int, int, dict[str, Any]]] = []
        old_files = set(dataset.get("source_candidates") or [])
        old_sheets = set(dataset.get("sheet_candidates") or [])
        for profile in profiles:
            available = set(profile.get("columns", []))
            matches = 0
            for field in required_fields:
                choices = [field.get("physical_name"), *(field.get("aliases") or [])]
                if any(choice and choice in available for choice in choices):
                    matches += 1
            name_bonus = int(profile.get("file_name") in old_files) + int(profile.get("sheet_name") in old_sheets)
            scored.append((matches, name_bonus, profile))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

        if not scored or scored[0][0] == 0:
            drift.append(SchemaDriftItem(
                code="DATASET_NOT_FOUND",
                severity="blocking",
                dataset_id=dataset_id,
                expected=", ".join(f.get("physical_name") or f.get("logical_name", "") for f in required_fields),
                observed="No candidate sheet contains contract fields",
                suggested_action="Use the Harness to propose evidence-backed logical-to-physical mappings; reviewer approval and a blueprint revision are required.",
            ))
            continue

        best_score, best_bonus, best_profile = scored[0]
        if len(scored) > 1 and scored[1][:2] == (best_score, best_bonus):
            drift.append(SchemaDriftItem(
                code="AMBIGUOUS_DATASET_MATCH",
                severity="blocking",
                dataset_id=dataset_id,
                observed=f"{best_profile['file_name']}::{best_profile.get('sheet_name') or 'CSV'} and another candidate have equal schema score",
                suggested_action="Reviewer must select the correct source dataset; do not combine equally matching extracts automatically.",
            ))
            continue

        # Check sheet visibility
        if best_profile.get("sheet_state") not in (None, "visible"):
            drift.append(SchemaDriftItem(
                code="HIDDEN_WORKSHEET_MATCHED",
                severity="warning",
                dataset_id=dataset_id,
                observed=f"Matched sheet '{best_profile.get('sheet_name')}' has state '{best_profile.get('sheet_state')}'",
                suggested_action="Confirm that the hidden worksheet contains authorized production extract data.",
                reviewer_required=True,
            ))

        # Check multiple snapshots
        if best_profile.get("multiple_snapshots_detected"):
            drift.append(SchemaDriftItem(
                code="MULTIPLE_SNAPSHOTS_DETECTED",
                severity="warning",
                dataset_id=dataset_id,
                observed="Multiple distinct version or snapshot values detected in source sample",
                suggested_action="Ensure reporting period / as-of filtering is applied per approved retrieval policy; do not union snapshots.",
                reviewer_required=True,
            ))

        col_profiles = best_profile.get("column_profiles", {})
        for field in required_fields:
            logical = field.get("logical_name")
            expected = field.get("physical_name")
            expected_type = field.get("data_type")
            aliases = field.get("aliases") or []
            available = set(best_profile.get("columns", []))
            matched = next((name for name in [expected, *aliases] if name and name in available), None)
            mappings.append({
                "dataset_id": dataset_id,
                "file_name": best_profile["file_name"],
                "sheet_name": best_profile.get("sheet_name"),
                "logical_field": logical,
                "expected_physical_field": expected,
                "observed_physical_field": matched,
                "mapping_state": field.get("mapping_state", "unknown"),
            })
            if not matched:
                drift.append(SchemaDriftItem(
                    code="REQUIRED_FIELD_MISSING",
                    severity="blocking",
                    dataset_id=dataset_id,
                    logical_field=logical,
                    expected=expected or " or ".join(aliases),
                    observed="not found",
                    suggested_action="Propose a mapping using semantic, type, domain and key evidence; reviewer approval required.",
                ))
            elif matched != expected or field.get("mapping_state") != "observed":
                drift.append(SchemaDriftItem(
                    code="FIELD_MAPPING_REQUIRES_REVIEW",
                    severity="warning",
                    dataset_id=dataset_id,
                    logical_field=logical,
                    expected=expected or "observed source mapping",
                    observed=matched,
                    suggested_action="Validate type, domain, uniqueness, date semantics and business meaning before accepting this mapping.",
                    auto_mapping_candidate=matched,
                    reviewer_required=True,
                ))

            # Type checking if specified
            if matched and expected_type:
                inferred = col_profiles.get(matched, {}).get("inferred_type")
                if inferred and inferred not in ("empty", "string") and expected_type.lower() != inferred:
                    drift.append(SchemaDriftItem(
                        code="FIELD_TYPE_DRIFT",
                        severity="warning",
                        dataset_id=dataset_id,
                        logical_field=logical,
                        expected=expected_type,
                        observed=inferred,
                        suggested_action=f"Verify field data type conversion ({inferred} to {expected_type}).",
                        reviewer_required=True,
                    ))

        # Check entity key uniqueness
        entity_keys = dataset.get("entity_key") or []
        for ek in entity_keys:
            if ek in col_profiles and not col_profiles[ek].get("is_candidate_key", False):
                drift.append(SchemaDriftItem(
                    code="KEY_UNIQUENESS_UNCERTAIN",
                    severity="warning",
                    dataset_id=dataset_id,
                    observed=f"Key column '{ek}' contains non-unique values in sample",
                    suggested_action="Check whether deduplication or latest-record filtering is required.",
                    reviewer_required=True,
                ))

        mappings.append({
            "dataset_id": dataset_id,
            "dataset_match": {
                "file_name": best_profile["file_name"],
                "sheet_name": best_profile.get("sheet_name"),
                "row_count": best_profile.get("row_count"),
                "header_row_index": best_profile.get("header_row_index"),
                "schema_score": best_score,
            },
        })

    blocking = any(item.severity == "blocking" for item in drift)
    warning = bool(drift)
    return GenerationCompatibilityReport(
        generation_id=generation_id,
        blueprint_id=blueprint.get("blueprint_id", ""),
        blueprint_version=int(blueprint.get("version", 1)),
        status="blocked" if blocking else ("compatible_with_warnings" if warning else "compatible"),
        source_manifest_hash=source_manifest_hash,
        source_profiles=profiles,
        mappings=mappings,
        drift=drift,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
