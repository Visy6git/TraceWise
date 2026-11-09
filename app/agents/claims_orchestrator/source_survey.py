"""All-source intelligence and knowledge artifact interfaces."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.analytics import default_analytics
from app.services.extraction import extract_source_file
from app.services.storage import default_storage


def survey_all_sources(run_id: str, source_files: list[str | Path]) -> dict[str, Any]:
    """Profile all uploaded source workbooks and generate canonical knowledge artifacts."""
    source_objects = []
    datasets = []
    columns = []
    relationships = []
    dataframes: dict[str, Any] = {}

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

        # Profile each sheet/dataset
        for ds in extracted["datasets"]:
            sheet_name = ds["sheet_or_table"]
            try:
                df = default_analytics.load_dataset(p, sheet_name=sheet_name)
                dataset_id = ds["dataset_id"]
                dataframes[dataset_id] = df

                profile = default_analytics.profile_dataframe(df, dataset_id)
                datasets.append({
                    "dataset_id": dataset_id,
                    "source_id": extracted["source_id"],
                    "sheet_or_table": sheet_name,
                    "visible": True,
                    "row_count": profile["row_count"],
                    "column_count": profile["column_count"],
                    "data_columns": [c["original_name"] for c in profile["columns"]],
                    "candidate_key_columns": profile["candidate_keys"],
                    "warnings": [],
                })
                columns.extend(profile["columns"])
            except Exception as e:
                datasets.append({
                    "dataset_id": ds["dataset_id"],
                    "source_id": extracted["source_id"],
                    "sheet_or_table": sheet_name,
                    "visible": True,
                    "row_count": ds["row_count"],
                    "column_count": len(ds["columns"]),
                    "data_columns": ds["columns"],
                    "candidate_key_columns": [],
                    "warnings": [f"Profiling warning: {e}"],
                })

    # Test relationships between datasets that share candidate keys or common ID columns
    ds_ids = list(dataframes.keys())
    for i in range(len(ds_ids)):
        for j in range(i + 1, len(ds_ids)):
            id_a = ds_ids[i]
            id_b = ds_ids[j]
            df_a = dataframes[id_a]
            df_b = dataframes[id_b]

            common_cols = [c for c in df_a.columns if c in df_b.columns and ("id" in c.lower() or "number" in c.lower() or "study" in c.lower())]
            for col in common_cols:
                try:
                    rel = default_analytics.test_join_cardinality(df_a, df_b, [col], [col])
                    relationships.append({
                        "left_dataset_id": id_a,
                        "right_dataset_id": id_b,
                        "join_keys": [col],
                        "tested_cardinality": rel["tested_cardinality"],
                        "overlap_count": rel["matched_rows"],
                        "unmatched_left_count": rel["unmatched_left"],
                        "unmatched_right_count": rel["unmatched_right"],
                        "duplicate_expansion": rel["duplicate_expansion"],
                        "evidence_refs": [id_a, id_b],
                    })
                except Exception:
                    pass

    # Build human-readable Markdown summary
    md_lines = [
        f"# Source Intelligence Survey for Run `{run_id}`",
        "",
        "## Uploaded Sources Overview",
        "",
        "| Source | Format | Size | Datasets / Sheets |",
        "|---|---|---|---|",
    ]
    for so in source_objects:
        ds_for_so = [d["sheet_or_table"] for d in datasets if d["source_id"] == so["source_id"]]
        md_lines.append(f"| {so['original_filename']} | {so['format']} | {so['size_bytes']} B | {', '.join(ds_for_so)} |")

    md_lines.extend(["", "## Detailed Datasets", ""])
    for d in datasets:
        md_lines.append(f"### Dataset `{d['dataset_id']}` (Sheet: `{d['sheet_or_table']}`)")
        md_lines.append(f"- **Rows**: {d['row_count']}")
        md_lines.append(f"- **Columns**: {', '.join(d['data_columns'])}")
        if d['candidate_key_columns']:
            md_lines.append(f"- **Candidate Keys**: {', '.join(d['candidate_key_columns'])}")
        md_lines.append("")

    if relationships:
        md_lines.extend(["## Detected Join Relationships", ""])
        for r in relationships:
            md_lines.append(
                f"- `{r['left_dataset_id']}` <-> `{r['right_dataset_id']}` on `{r['join_keys']}`: "
                f"Cardinality `{r['tested_cardinality']}`, Overlap: {r['overlap_count']}"
            )
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

    # Store manifests in storage
    default_storage.put_immutable(
        tenant_id="default",
        run_id=run_id,
        logical_path="extracted/source_extraction_manifest.json",
        body=json.dumps({"sources": source_objects}, indent=2),
    )
    default_storage.put_immutable(
        tenant_id="default",
        run_id=run_id,
        logical_path="stage_1_claims/source_knowledge.json",
        body=json.dumps(source_knowledge_data, indent=2),
    )
    default_storage.put_immutable(
        tenant_id="default",
        run_id=run_id,
        logical_path="stage_1_claims/source_knowledge.md",
        body=source_knowledge_md,
    )
    default_storage.put_immutable(
        tenant_id="default",
        run_id=run_id,
        logical_path="stage_1_claims/schema_profiles.json",
        body=json.dumps(datasets, indent=2),
    )
    default_storage.put_immutable(
        tenant_id="default",
        run_id=run_id,
        logical_path="stage_1_claims/relationships.json",
        body=json.dumps(relationships, indent=2),
    )
    default_storage.put_immutable(
        tenant_id="default",
        run_id=run_id,
        logical_path="stage_1_claims/knowledge_graph.json",
        body=json.dumps({"nodes": datasets, "edges": relationships}, indent=2),
    )

    return source_knowledge_data
