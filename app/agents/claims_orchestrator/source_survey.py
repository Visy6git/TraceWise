"""All-source intelligence and knowledge artifact generation.

Builds a *source map* the downstream agents can actually act on: for every data
sheet it records the real header row, the real column names, each column's type
and — for low-cardinality columns — the full set of distinct values (so a filter
like ``Seriousness == 'Yes'`` can be specified exactly). The stated totals in the
sheet preamble (e.g. "Count of Cases: 164") are captured too.

Profiling reads a bounded sample via openpyxl using the detected header offset,
so the multi-MB "all CSMR" exports do not stall the stage.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import openpyxl

from app.services.event_stream import default_broker
from app.services.extraction import extract_source_file
from app.services.storage import default_storage

_PROFILE_SAMPLE_ROWS = 3000
_MAX_DISTINCT = 25
_SNIPPET = 80


def _guess_type(samples: list[Any]) -> str:
    values = [v for v in samples if v not in (None, "")]
    if not values:
        return "unknown"
    numeric = 0
    for v in values:
        try:
            float(str(v).replace(",", ""))
            numeric += 1
        except (TypeError, ValueError):
            break
    return "numeric" if numeric == len(values) else "string"


def _is_keyish(name: str) -> bool:
    n = name.lower()
    return n == "id" or n.endswith("_id") or "case number" in n or "case_number" in n or n.endswith("number")


def _profile_columns(path: Path, dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-column profile: type, fill, distinct values (for categorical columns)."""
    cols = dataset["columns"]
    header_idx = dataset.get("header_row_index", 0)
    value_sets: list[set] = [set() for _ in cols]
    overflow = [False] * len(cols)
    non_null = [0] * len(cols)
    sampled = 0

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        ws = wb[dataset["sheet_or_table"]]
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i <= header_idx:
                continue
            if sampled >= _PROFILE_SAMPLE_ROWS:
                break
            if not any(c is not None and str(c).strip() for c in row):
                continue
            sampled += 1
            for j in range(len(cols)):
                v = row[j] if j < len(row) else None
                if v is None or not str(v).strip():
                    continue
                non_null[j] += 1
                if not overflow[j]:
                    value_sets[j].add(str(v).strip()[:_SNIPPET])
                    if len(value_sets[j]) > _MAX_DISTINCT:
                        overflow[j] = True
    finally:
        wb.close()

    profiles: list[dict[str, Any]] = []
    for j, name in enumerate(cols):
        vals = sorted(value_sets[j])
        categorical = not overflow[j] and 0 < len(vals) <= _MAX_DISTINCT
        profiles.append({
            "name": str(name),
            "type": _guess_type(vals[:12]),
            "non_null": non_null[j],
            "sampled_rows": sampled,
            "distinct_estimate": f">{_MAX_DISTINCT}" if overflow[j] else len(vals),
            "is_categorical": categorical,
            "distinct_values": vals if categorical else None,
            "example_values": vals[:6],
        })
    return profiles


def survey_all_sources(run_id: str, source_files: list[str | Path]) -> dict[str, Any]:
    """Profile all uploaded source workbooks and generate canonical knowledge artifacts."""
    source_objects: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []

    for src_path in source_files:
        p = Path(src_path).resolve()
        extracted = extract_source_file(p)
        source_objects.append({
            "source_id": extracted["source_id"],
            "original_filename": extracted["filename"],
            "object_id": f"default/{run_id}/sources/{extracted['filename']}",
            "sha256": extracted["sha256"],
            "format": extracted["format"],
            "size_bytes": extracted["size_bytes"],
            "extraction_status": "complete",
            "physical_path": str(p),
            "limitations": [],
        })

        data_sheets = [d for d in extracted["datasets"] if d.get("is_data")]
        default_broker.emit_activity(
            run_id=run_id, stage="claims", title="Profiling source",
            detail=f"{extracted['filename']} · {len(data_sheets)} data sheet(s)",
            kind="tool", source=extracted["filename"],
        )

        for ds in data_sheets:
            dataset_id = ds["dataset_id"]
            col_names = [str(c) for c in ds["columns"]]
            try:
                col_profiles = _profile_columns(p, ds)
            except Exception as exc:  # profiling must not sink the stage
                col_profiles = [{"name": c, "type": "unknown"} for c in col_names]
                default_broker.emit_activity(
                    run_id=run_id, stage="claims", title="Profiling warning",
                    detail=f"{extracted['filename']} / {ds['sheet_or_table']}: {exc}",
                    kind="warning", status="warning",
                )
            candidate_keys = [c for c in col_names if _is_keyish(c)]

            for prof in col_profiles:
                columns.append({
                    "dataset_id": dataset_id,
                    "original_name": prof["name"],
                    "normalized_name": prof["name"].lower().replace(" ", "_"),
                    "inferred_type": prof["type"],
                    "is_categorical": prof.get("is_categorical", False),
                    "distinct_values": prof.get("distinct_values"),
                    "sample_values": prof.get("example_values", []),
                })

            datasets.append({
                "dataset_id": dataset_id,
                "source_id": extracted["source_id"],
                "sheet_or_table": ds["sheet_or_table"],
                "header_row_index": ds.get("header_row_index", 0),
                "visible": True,
                "row_count": ds["row_count"],
                "column_count": len(col_names),
                "data_columns": col_names,
                "candidate_key_columns": candidate_keys,
                "preamble": ds.get("preamble", []),
                "column_profiles": col_profiles,
                "warnings": [],
            })

    # Heuristic relationships: data sheets sharing a key-ish column likely join on it.
    for i in range(len(datasets)):
        for j in range(i + 1, len(datasets)):
            shared = [
                c for c in datasets[i]["candidate_key_columns"]
                if c in datasets[j]["candidate_key_columns"]
            ]
            for col in shared[:1]:
                relationships.append({
                    "left_dataset_id": datasets[i]["dataset_id"],
                    "right_dataset_id": datasets[j]["dataset_id"],
                    "join_keys": [col],
                    "tested_cardinality": "inferred_shared_key",
                    "evidence_refs": [datasets[i]["dataset_id"], datasets[j]["dataset_id"]],
                })

    # Human-readable Markdown summary
    md_lines = [
        f"# Source Intelligence Survey for Run `{run_id}`",
        "",
        "## Uploaded Sources Overview",
        "",
        "| Source | Format | Size | Data sheets |",
        "|---|---|---|---|",
    ]
    for so in source_objects:
        ds_for_so = [d["sheet_or_table"] for d in datasets if d["source_id"] == so["source_id"]]
        md_lines.append(f"| {so['original_filename']} | {so['format']} | {so['size_bytes']} B | {', '.join(ds_for_so)} |")
    md_lines.extend(["", "## Data Sheets", ""])
    for d in datasets:
        md_lines.append(f"### `{d['dataset_id']}` (sheet `{d['sheet_or_table']}`, header row {d['header_row_index']})")
        md_lines.append(f"- **Rows**: {d['row_count']}")
        if d.get("preamble"):
            md_lines.append(f"- **Stated in sheet**: {'; '.join(d['preamble'][:4])}")
        if d["candidate_key_columns"]:
            md_lines.append(f"- **Candidate keys**: {', '.join(d['candidate_key_columns'])}")
        cats = [p for p in d["column_profiles"] if p.get("is_categorical")]
        if cats:
            md_lines.append("- **Categorical columns (exact filter values):**")
            for p in cats[:12]:
                md_lines.append(f"    - `{p['name']}` ∈ {p['distinct_values']}")
        md_lines.append(f"- **All columns**: {', '.join(d['data_columns'])}")
        md_lines.append("")
    source_knowledge_md = "\n".join(md_lines)

    source_knowledge_data = {
        "schema_version": "1.0",
        "run_id": run_id,
        "sources": source_objects,
        "datasets": datasets,
        "columns": columns,
        "relationships": relationships,
        "filter_evidence": [],
        "global_limitations": [],
    }

    for logical_path, body in [
        ("extracted/source_extraction_manifest.json", json.dumps({"sources": source_objects}, indent=2)),
        ("stage_1_claims/source_knowledge.json", json.dumps(source_knowledge_data, indent=2)),
        ("stage_1_claims/source_knowledge.md", source_knowledge_md),
        ("stage_1_claims/schema_profiles.json", json.dumps(datasets, indent=2)),
        ("stage_1_claims/relationships.json", json.dumps(relationships, indent=2)),
        ("stage_1_claims/knowledge_graph.json", json.dumps({"nodes": datasets, "edges": relationships}, indent=2)),
    ]:
        default_storage.put_derived(tenant_id="default", run_id=run_id, logical_path=logical_path, body=body)

    return source_knowledge_data
