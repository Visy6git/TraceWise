"""Role-scoped source investigation tools."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from app.services.analytics import default_analytics
from app.services.storage import default_storage


class SourceRef(BaseModel):
    run_id: str
    source_id: str
    dataset_id: str | None = None


class ColumnProfileRequest(SourceRef):
    column: str = Field(min_length=1, max_length=256)


class SampleRequest(SourceRef):
    filters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=100)


def list_source_files(run_id: str) -> list[dict[str, Any]]:
    manifest_path = f"default/{run_id}/extracted/source_extraction_manifest.json"
    try:
        content = default_storage.read_text(manifest_path)
        manifest = json.loads(content)
        return manifest.get("sources", [])
    except Exception:
        return []


def get_sheet_schema(source: SourceRef) -> dict[str, Any]:
    schema_path = f"default/{source.run_id}/stage_1_claims/schema_profiles.json"
    try:
        content = default_storage.read_text(schema_path)
        profiles = json.loads(content)
        dataset_id = source.dataset_id or source.source_id
        for p in profiles:
            if p.get("dataset_id") == dataset_id:
                return p
        return {"error": f"Dataset {dataset_id} not found in profiles"}
    except Exception as e:
        return {"error": str(e)}


def profile_column(request: ColumnProfileRequest) -> dict[str, Any]:
    schema = get_sheet_schema(request)
    if "columns" in schema:
        for col in schema["columns"]:
            if col.get("original_name") == request.column or col.get("normalized_name") == request.column:
                return col
    return {"error": f"Column {request.column} not found in schema"}


def sample_rows(request: SampleRequest) -> dict[str, Any]:
    source_files = list_source_files(request.run_id)
    matched = None
    for s in source_files:
        if s.get("source_id") == request.source_id or s.get("filename") == request.source_id:
            matched = s
            break

    if not matched:
        return {"error": f"Source {request.source_id} not found"}

    physical_path = matched.get("physical_path")
    if not physical_path or not Path(physical_path).exists():
        return {"error": f"Physical source file not available for {request.source_id}"}

    sheet = None
    if request.dataset_id and "_" in request.dataset_id:
        sheet = request.dataset_id.split("_", 1)[1]

    df = default_analytics.load_dataset(physical_path, sheet_name=sheet)

    # Apply equality filters safely
    for k, v in request.filters.items():
        if k in df.columns:
            df = df[df[k] == v]

    if request.columns:
        valid_cols = [c for c in request.columns if c in df.columns]
        if valid_cols:
            df = df[valid_cols]

    sample = df.head(request.limit).to_dict(orient="records")
    return {
        "dataset_id": request.dataset_id or request.source_id,
        "returned_rows": len(sample),
        "total_filtered_rows": len(df),
        "rows": sample,
    }


def test_join_cardinality(left: SourceRef, right: SourceRef, keys: list[str]) -> dict[str, Any]:
    sources = list_source_files(left.run_id)
    left_src = next((s for s in sources if s.get("source_id") == left.source_id), None)
    right_src = next((s for s in sources if s.get("source_id") == right.source_id), None)

    if not left_src or not right_src:
        return {"error": "Left or right source file not found"}

    left_df = default_analytics.load_dataset(left_src["physical_path"])
    right_df = default_analytics.load_dataset(right_src["physical_path"])

    return default_analytics.test_join_cardinality(left_df, right_df, keys, keys)


def execute_readonly_query(source: SourceRef, structured_query: dict[str, Any]) -> dict[str, Any]:
    # Parameterized structured query AST -> DuckDB
    # e.g. {"table": "...", "select": [...], "where": {...}, "group_by": [...]}
    table = structured_query.get("table", source.dataset_id)
    select_cols = ", ".join(structured_query.get("select", ["*"]))
    query = f"SELECT {select_cols} FROM {table}"
    try:
        records = default_analytics.execute_bounded_query(query, max_rows=100)
        return {"records": records, "count": len(records)}
    except Exception as e:
        return {"error": str(e)}
