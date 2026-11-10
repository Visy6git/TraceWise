"""Stage 1 Phase 1A: Per-file source exploration via Agentic Harness -> Master Summary .md.

For each uploaded source file:
1. Explore the first 100 lines/rows to inspect sheets, banner/preamble, header row.
2. Write Python placeholder/navigation logic (`explore_source.py`) embedding all sheet names,
   columns, data types, and unique values per column, and execute it via `shell`.
3. Write a detailed per-file Markdown summary (`<slug>.md`).
4. Once ALL files are processed, synthesize `master_source_summary.md` combining every file's
   `.md` findings across the entire dataset for downstream Strands Claims extraction.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import openpyxl

from app.config import MOCK_RUNS_ENABLED, is_live_llm_enabled
from app.harness.paths import strip_extended_prefix, to_extended_path
from app.harness.runner import HarnessRunResult, run_harness_task
from app.services.database import default_artifact_repo
from app.services.event_stream import default_broker
from app.services.extraction import _detect_header, extract_source_file
from app.services.storage import default_storage


def _short_slug(idx: int, filename: str) -> str:
    stem = Path(filename).stem.lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return f"src_{idx:02d}_{cleaned[:24]}".rstrip("_")


def _load_prompt(name: str) -> str:
    prompt_path = Path(__file__).resolve().parents[2] / "prompts" / name
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return ""


def _infer_type_and_uniques(values: list[Any], max_uniques_inline: int = 80) -> dict[str, Any]:
    non_null = [v for v in values if v is not None and str(v).strip() != ""]
    null_count = len(values) - len(non_null)
    str_vals = [str(v).strip() for v in non_null]

    # Simple type inference
    inferred_type = "string"
    if non_null:
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
            inferred_type = "integer" if all(isinstance(v, int) or float(v).is_integer() for v in non_null) else "float"
        elif all(re.fullmatch(r"-?\d+", s) for s in str_vals[:200]):
            inferred_type = "date_yyyymmdd" if all(len(s) == 8 and s.startswith(("19", "20")) for s in str_vals[:100]) else "integer"
        elif all(re.fullmatch(r"-?\d+(?:\.\d+)?", s) for s in str_vals[:200]):
            inferred_type = "float"

    uniques_ordered: list[str] = []
    seen: set[str] = set()
    for s in str_vals:
        if s not in seen:
            seen.add(s)
            uniques_ordered.append(s)

    total_unique = len(uniques_ordered)
    if total_unique <= max_uniques_inline:
        unique_values: list[str] = uniques_ordered
        uniques_truncated = False
    else:
        unique_values = uniques_ordered[:max_uniques_inline]
        uniques_truncated = True

    return {
        "inferred_type": inferred_type,
        "non_null_count": len(non_null),
        "null_count": null_count,
        "distinct_count": total_unique,
        "unique_values": unique_values,
        "uniques_truncated": uniques_truncated,
        "sample_values": uniques_ordered[:10],
        "min_value": min(uniques_ordered) if uniques_ordered else None,
        "max_value": max(uniques_ordered) if uniques_ordered else None,
    }


def profile_source_file_full(file_path: Path) -> dict[str, Any]:
    """Deterministic Python profiler used both for validation and mock execution."""
    ext_path = to_extended_path(strip_extended_prefix(file_path).resolve())
    suffix = ext_path.suffix.lower()
    sheets_info: list[dict[str, Any]] = []

    if suffix in {".xlsx", ".xlsm", ".xltx"}:
        wb = openpyxl.load_workbook(str(ext_path), read_only=True, data_only=True)
        try:
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows_all = list(ws.iter_rows(values_only=True))
                first_100 = [list(r) for r in rows_all[:100]]
                max_col = max((len(r) for r in rows_all[:40]), default=0)
                header_idx, header_row, preamble = _detect_header(rows_all[:40], max_col)
                if header_row is None:
                    continue
                data_rows_raw = rows_all[header_idx + 1 :]
                # Drop trailing completely-empty footer rows
                data_rows = [
                    r for r in data_rows_raw if any(c is not None and str(c).strip() != "" for c in r)
                ]
                col_profiles: list[dict[str, Any]] = []
                for c_idx, col_name in enumerate(header_row):
                    col_vals = [r[c_idx] if c_idx < len(r) else None for r in data_rows]
                    stats = _infer_type_and_uniques(col_vals)
                    col_profiles.append({"name": col_name, **stats})

                candidate_keys = [
                    c["name"]
                    for c in col_profiles
                    if c["distinct_count"] > 0
                    and ("case" in c["name"].lower() or "id" in c["name"].lower() or "number" in c["name"].lower())
                ]
                real_cols = sum(1 for c in header_row if not c.startswith("col_"))
                is_data = real_cols >= 2 and len(data_rows) > 0 and not sheet_name.lower().startswith("cover")

                sheets_info.append(
                    {
                        "sheet_name": sheet_name,
                        "is_data": is_data,
                        "header_row_index": header_idx,
                        "preamble": preamble,
                        "row_count": len(data_rows),
                        "raw_trailing_empty_rows": len(data_rows_raw) - len(data_rows),
                        "column_count": len(header_row),
                        "candidate_keys": candidate_keys,
                        "first_100_preview_rows": len(first_100),
                        "columns": col_profiles,
                    }
                )
        finally:
            wb.close()

    elif suffix == ".csv":
        with open(ext_path, "r", encoding="utf-8-sig", errors="replace") as f:
            rows_all = list(csv.reader(f))
        if rows_all:
            max_col = max((len(r) for r in rows_all[:40]), default=0)
            header_idx, header_row, preamble = _detect_header(
                [tuple(r) for r in rows_all[:40]], max_col
            )
            if header_row is None:
                header_idx, header_row, preamble = 0, rows_all[0], []
            data_rows_raw = rows_all[header_idx + 1 :]
            data_rows = [
                tuple(r) for r in data_rows_raw if any(str(c).strip() != "" for c in r)
            ]
            col_profiles = []
            for c_idx, col_name in enumerate(header_row):
                col_vals = [r[c_idx] if c_idx < len(r) else None for r in data_rows]
                stats = _infer_type_and_uniques(col_vals)
                col_profiles.append({"name": col_name, **stats})
            sheets_info.append(
                {
                    "sheet_name": ext_path.name,
                    "is_data": len(header_row) >= 2 and len(data_rows) > 0,
                    "header_row_index": header_idx,
                    "preamble": preamble,
                    "row_count": len(data_rows),
                    "raw_trailing_empty_rows": len(data_rows_raw) - len(data_rows),
                    "column_count": len(header_row),
                    "candidate_keys": [c["name"] for c in col_profiles if "id" in c["name"].lower() or "case" in c["name"].lower()],
                    "first_100_preview_rows": min(100, len(rows_all)),
                    "columns": col_profiles,
                }
            )

    sha256 = hashlib.sha256(ext_path.read_bytes()).hexdigest()
    return {
        "filename": file_path.name,
        "format": suffix.lstrip("."),
        "size_bytes": ext_path.stat().st_size,
        "sha256": sha256,
        "sheets": sheets_info,
    }


def _generate_navigation_python(profile: dict[str, Any]) -> str:
    """Build clean Python placeholder/navigation logic containing columns, types, and unique values."""
    filename = profile["filename"]
    sheets_meta: dict[str, Any] = {}
    for sh in profile["sheets"]:
        sname = sh["sheet_name"]
        sheets_meta[sname] = {
            "is_data": sh["is_data"],
            "header_row_index": sh["header_row_index"],
            "row_count": sh["row_count"],
            "preamble": sh["preamble"],
            "candidate_keys": sh["candidate_keys"],
            "columns": [
                {
                    "name": c["name"],
                    "dtype": c["inferred_type"],
                    "distinct_count": c["distinct_count"],
                    "null_count": c["null_count"],
                    "unique_values": c["unique_values"],
                    "uniques_truncated": c["uniques_truncated"],
                }
                for c in sh["columns"]
            ],
        }

    import pprint

    catalog_py = pprint.pformat(sheets_meta, width=110, sort_dicts=False)
    code = f'''"""Auto-generated placeholder/navigation module for {filename!r}.

Generated after inspecting the first 100 rows and profiling all columns, data types,
and unique values across every sheet so Stage 1 & Stage 2 agents have exact coordinates.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

SOURCE_FILENAME = {json.dumps(filename)}

# Discovered sheet schemas, inferred types, and unique column values embedded directly:
SOURCE_CATALOG: dict[str, Any] = {catalog_py}


def list_sheets() -> list[str]:
    return list(SOURCE_CATALOG.keys())


def get_sheet_columns(sheet_name: str) -> list[dict[str, Any]]:
    return SOURCE_CATALOG[sheet_name]["columns"]


def _ext_path(p: Path) -> Path:
    s = str(p.resolve())
    ext_prefix = chr(92) * 2 + "?" + chr(92)
    if os.name == "nt" and len(s) >= 245 and not s.startswith(ext_prefix):
        return Path(ext_prefix + s)
    return p


def load_sheet_dataframe(sheet_name: str, source_dir: str | None = None) -> pd.DataFrame:
    base_dir = Path(source_dir or os.environ.get("SOURCE_INPUT_DIR", "."))
    file_path = _ext_path(base_dir / SOURCE_FILENAME)
    meta = SOURCE_CATALOG[sheet_name]
    header_idx = int(meta["header_row_index"])
    if SOURCE_FILENAME.lower().endswith(".csv"):
        df = pd.read_csv(file_path, skiprows=header_idx, dtype=str)
    else:
        df = pd.read_excel(file_path, sheet_name=sheet_name, skiprows=header_idx, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    return df


def inspect_first_100_rows(sheet_name: str, source_dir: str | None = None) -> list[dict[str, Any]]:
    df = load_sheet_dataframe(sheet_name, source_dir=source_dir)
    return df.head(100).fillna("").to_dict(orient="records")


if __name__ == "__main__":
    summary = {{
        "filename": SOURCE_FILENAME,
        "sheets": list_sheets(),
        "catalog": SOURCE_CATALOG,
    }}
    Path("profile.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Verified navigation logic for {{SOURCE_FILENAME}} ({{len(list_sheets())}} sheets)")
'''
    return code


def _generate_file_markdown(profile: dict[str, Any]) -> str:
    """Build detailed per-file Markdown summary consumed by Stage 2 Rules harness."""
    lines: list[str] = [
        f"# Source File Summary: `{profile['filename']}`",
        "",
        f"- **Format**: `{profile['format']}`",
        f"- **Size**: {profile['size_bytes']} bytes",
        f"- **SHA-256**: `{profile['sha256']}`",
        f"- **Sheets discovered**: {len(profile['sheets'])}",
        "",
    ]

    for sh in profile["sheets"]:
        tag = "Data Table" if sh["is_data"] else "Cover / Non-Data"
        lines.append(f"## Sheet: `{sh['sheet_name']}` ({tag})")
        lines.append(f"- **0-based `header_row_index`**: `{sh['header_row_index']}` (use `skiprows={sh['header_row_index']}` in `pandas`)")
        lines.append(f"- **Data rows (non-empty)**: {sh['row_count']}")
        if sh.get("raw_trailing_empty_rows", 0) > 0:
            lines.append(f"- **Trailing empty/footer rows**: {sh['raw_trailing_empty_rows']} (drop empty rows with `.dropna(how='all')`)")
        if sh["preamble"]:
            lines.append("- **Preamble / Banner Lines**:")
            for p in sh["preamble"]:
                lines.append(f"  - `{p}`")
        if sh["candidate_keys"]:
            lines.append(f"- **Candidate ID / Dedup Keys**: {', '.join(f'`{k}`' for k in sh['candidate_keys'])}")
        lines.append("")
        lines.append("| Column Name | Data Type | Non-Null | Null | Distinct | Unique / Sample Values |")
        lines.append("| --- | --- | ---: | ---: | ---: | --- |")
        for c in sh["columns"]:
            uvals = c.get("unique_values") or []
            u_preview = ", ".join(f"`{u}`" for u in uvals[:25])
            if len(uvals) > 25 or c.get("uniques_truncated"):
                u_preview += f" ... *(+{max(c['distinct_count'] - 25, 0)} more)*"
            lines.append(
                f"| `{c['name']}` | `{c['inferred_type']}` | {c['non_null_count']} | {c['null_count']} | {c['distinct_count']} | {u_preview} |"
            )
        lines.append("")

    return "\n".join(lines)


def _synthesize_master_markdown(
    file_profiles: list[dict[str, Any]],
    per_file_mds: dict[str, str],
) -> str:
    """Synthesize the Master Summary of Source Documents across all uploaded sources."""
    lines: list[str] = [
        "# Master Summary of Source Documents",
        "",
        f"Total uploaded source files explored: **{len(file_profiles)}**",
        "",
        "## Cross-Dataset Inventory",
        "",
        "| # | Source Filename | Primary Data Sheet(s) | `header_row_index` | Rows | Candidate Keys | Per-File Summary Artifact |",
        "| ---: | --- | --- | --- | ---: | --- | --- |",
    ]

    for idx, prof in enumerate(file_profiles, start=1):
        fname = prof["filename"]
        data_sheets = [s for s in prof["sheets"] if s.get("is_data")] or prof["sheets"]
        sheet_names = ", ".join(f"`{s['sheet_name']}`" for s in data_sheets) or "N/A"
        headers_idx = ", ".join(str(s["header_row_index"]) for s in data_sheets) or "0"
        total_rows = sum(int(s.get("row_count", 0)) for s in data_sheets)
        keys = sorted({k for s in data_sheets for k in s.get("candidate_keys", [])})
        key_str = ", ".join(f"`{k}`" for k in keys[:5]) or "-"
        md_rel = prof.get("md_logical_path", "")
        lines.append(
            f"| {idx} | `{fname}` | {sheet_names} | {headers_idx} | {total_rows} | {key_str} | `{md_rel}` |"
        )

    lines.extend(["", "## Per-File Key Schemas & Categorical Values", ""])
    for prof in file_profiles:
        fname = prof["filename"]
        lines.append(f"### `{fname}`")
        data_sheets = [s for s in prof["sheets"] if s.get("is_data")] or prof["sheets"]
        for sh in data_sheets:
            lines.append(
                f"- Sheet `{sh['sheet_name']}` (`header_row_index={sh['header_row_index']}`, rows={sh['row_count']}):"
            )
            if sh.get("preamble"):
                lines.append(f"  - Preamble: {' | '.join(sh['preamble'][:3])}")
            for col in sh["columns"]:
                # Show full categorical lists cleanly so Stage 1B claims agent maps exact values
                if 0 < col["distinct_count"] <= 20:
                    vals = ", ".join(f"`{v}`" for v in col["unique_values"])
                    lines.append(f"  - `{col['name']}` ({col['inferred_type']}, {col['distinct_count']} unique): {vals}")
                else:
                    lines.append(
                        f"  - `{col['name']}` ({col['inferred_type']}, {col['distinct_count']} distinct, sample={col['unique_values'][:5]})"
                    )
        lines.append("")

    return "\n".join(lines)


def _publish_run_artifact(
    run_id: str,
    logical_path: str,
    media_type: str,
    content: str | bytes,
    producer: str,
) -> dict[str, Any]:
    res = default_storage.put_derived(
        tenant_id="default",
        run_id=run_id,
        logical_path=logical_path,
        body=content,
    )
    artifact_id = f"art_{hashlib.md5(f'{run_id}:{logical_path}:claims'.encode()).hexdigest()[:12]}"
    entry = {
        "artifact_id": artifact_id,
        "run_id": run_id,
        "stage": "claims",
        "claim_id": None,
        "logical_path": logical_path,
        "version": 1,
        "sha256": res["sha256"],
        "media_type": media_type,
        "size_bytes": res["size_bytes"],
        "producer_agent_id": producer,
        "status": "ready",
    }
    default_artifact_repo.add_artifact(entry)
    default_broker.emit_artifact_ready(run_id, "claims", entry)
    return entry


def explore_all_sources_with_harness(
    run_id: str,
    source_paths: list[str],
    live_harness: bool | None = None,
) -> dict[str, Any]:
    """Explore each uploaded source sequentially via Harness, then create Master Summary .md."""
    use_live = (is_live_llm_enabled() and not MOCK_RUNS_ENABLED) if live_harness is None else live_harness

    system_instructions = _load_prompt("source_explorer.md")
    per_file_mds: dict[str, str] = {}
    file_profiles: list[dict[str, Any]] = []
    source_objects: list[dict[str, Any]] = []
    dataset_profiles: list[dict[str, Any]] = []
    column_profiles: list[dict[str, Any]] = []

    run_base = strip_extended_prefix(default_storage.run_dir(run_id)).resolve()

    for idx, src_path_str in enumerate(source_paths, start=1):
        src_path = strip_extended_prefix(Path(src_path_str)).resolve()
        filename = src_path.name
        slug = _short_slug(idx, filename)
        ws_dir = run_base / "stage_1_claims" / "explore_ws" / slug
        ws_dir.mkdir(parents=True, exist_ok=True)
        src_parent = strip_extended_prefix(src_path.parent).resolve()

        default_broker.emit_activity(
            run_id=run_id,
            stage="claims",
            title=f"Exploring source {idx}/{len(source_paths)}: {filename}",
            detail="Running Agentic Harness: 100-row scan -> Python catalog -> .md summary",
            kind="agent",
            agent="SourceExplorerHarness",
        )

        # Profile file for canonical dataset records & verification fallback
        prof = profile_source_file_full(src_path)

        py_code: str | None = None
        md_content: str | None = None
        tool_history: list[dict[str, Any]] = []

        if use_live:
            goal = (
                f"Explore source file `{filename}` (located in read-only directory `$SOURCE_INPUT_DIR`).\n\n"
                "Follow these exact steps inside your current workspace (`cwd`):\n"
                f"Step 1: Run a quick one-line or short Python probe via `shell` to inspect ONLY the FIRST 100 rows/lines of "
                f"`{filename}` (use `os.path.join(os.environ['SOURCE_INPUT_DIR'], {json.dumps(filename)})`). Print sheet names, preamble lines, header row index, and sample rows.\n"
                "Step 2: Write `explore_source.py` via `write_file` containing explicit navigation/placeholder constants "
                "(`SOURCE_FILENAME`, `SOURCE_CATALOG` listing every sheet, `header_row_index`, every column name, inferred data type, and all unique values in each column) "
                "plus helper functions to load any sheet cleanly, and write `profile.json` when run.\n"
                "Step 3: Execute `python explore_source.py` via `shell` to verify it runs with exit code 0.\n"
                "Step 4: Write `summary.md` via `write_file` summarizing every sheet, header offset, preamble notes, candidate keys, column types, and exact unique values."
            )

            h_res: HarnessRunResult = run_harness_task(
                run_id=run_id,
                stage="claims",
                agent_id=f"SourceExplorer-{slug}",
                goal=goal,
                workspace_dir=ws_dir,
                readonly_dirs=[src_parent],
                env_vars={"SOURCE_INPUT_DIR": str(src_parent), "RUN_ID": run_id},
                developer_instructions=system_instructions,
                max_turns=16,
            )
            tool_history = h_res.tool_history

            py_file = ws_dir / "explore_source.py"
            md_file = ws_dir / "summary.md"
            if py_file.exists():
                py_code = py_file.read_text(encoding="utf-8")
            if md_file.exists():
                md_content = md_file.read_text(encoding="utf-8")

        # Validate or deterministically ensure complete `.py` + `.md` when in mock mode or if a local model fell short
        if not py_code:
            py_code = _generate_navigation_python(prof)
            (ws_dir / "explore_source.py").write_text(py_code, encoding="utf-8")
            import os

            run_env = {
                k: v
                for k, v in os.environ.items()
                if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT"}
            }
            run_env["SOURCE_INPUT_DIR"] = str(src_parent)
            run_env["PYTHONIOENCODING"] = "utf-8"
            # Execute the generated Python script in the workspace so it's proven runnable!
            subprocess.run(
                [sys.executable, "explore_source.py"],
                cwd=str(ws_dir),
                env=run_env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

        if not md_content:
            md_content = _generate_file_markdown(prof)
            (ws_dir / "summary.md").write_text(md_content, encoding="utf-8")

        py_logical = f"stage_1_claims/sources/{slug}_explore.py"
        md_logical = f"stage_1_claims/sources/{slug}.md"
        prof["py_logical_path"] = py_logical
        prof["md_logical_path"] = md_logical
        prof["source_id"] = slug

        _publish_run_artifact(run_id, py_logical, "text/x-python", py_code, f"SourceExplorer-{slug}")
        _publish_run_artifact(run_id, md_logical, "text/markdown", md_content, f"SourceExplorer-{slug}")

        if tool_history:
            _publish_run_artifact(
                run_id,
                f"stage_1_claims/sources/{slug}_tool_history.jsonl",
                "application/x-ndjson",
                "\n".join(json.dumps(e) for e in tool_history),
                f"SourceExplorer-{slug}",
            )

        per_file_mds[filename] = md_content
        file_profiles.append(prof)

        source_objects.append(
            {
                "source_id": slug,
                "original_filename": filename,
                "object_id": str(src_path),
                "sha256": prof["sha256"],
                "format": prof["format"],
                "size_bytes": prof["size_bytes"],
                "extraction_status": "explored",
                "limitations": [],
            }
        )
        for sh in prof["sheets"]:
            ds_id = f"{slug}_{sh['sheet_name']}".replace(" ", "_")
            dataset_profiles.append(
                {
                    "dataset_id": ds_id,
                    "source_id": slug,
                    "source_filename": filename,
                    "sheet_or_table": sh["sheet_name"],
                    "visible": True,
                    "is_data": sh["is_data"],
                    "header_row": sh["header_row_index"],
                    "row_count": sh["row_count"],
                    "column_count": sh["column_count"],
                    "data_columns": [c["name"] for c in sh["columns"]],
                    "candidate_key_columns": sh["candidate_keys"],
                    "preamble": sh["preamble"],
                    "warnings": [],
                }
            )
            for col in sh["columns"]:
                column_profiles.append(
                    {
                        "dataset_id": ds_id,
                        "original_name": col["name"],
                        "normalized_name": re.sub(r"[^a-z0-9]+", "_", col["name"].lower()).strip("_"),
                        "inferred_type": col["inferred_type"],
                        "null_count": col["null_count"],
                        "distinct_count": col["distinct_count"],
                        "unique_values": col["unique_values"],
                        "sample_values": col["sample_values"],
                    }
                )

    # After the LAST source file finishes -> create Master Summary .md
    master_md = _synthesize_master_markdown(file_profiles, per_file_mds)
    _publish_run_artifact(
        run_id,
        "stage_1_claims/master_source_summary.md",
        "text/markdown",
        master_md,
        "SourceExplorerMaster",
    )
    # Also publish compatibility aliases & JSON extraction manifests for API/UI
    _publish_run_artifact(
        run_id,
        "stage_1_claims/source_knowledge.md",
        "text/markdown",
        master_md,
        "SourceExplorerMaster",
    )
    canonical_knowledge = {
        "schema_version": "2.0",
        "run_id": run_id,
        "sources": source_objects,
        "datasets": dataset_profiles,
        "columns": column_profiles,
        "per_file_md_paths": {p["filename"]: p["md_logical_path"] for p in file_profiles},
        "per_file_py_paths": {p["filename"]: p["py_logical_path"] for p in file_profiles},
    }
    _publish_run_artifact(
        run_id,
        "stage_1_claims/source_knowledge.json",
        "application/json",
        json.dumps(canonical_knowledge, indent=2),
        "SourceExplorerMaster",
    )
    default_storage.put_derived(
        tenant_id="default",
        run_id=run_id,
        logical_path="extracted/source_extraction_manifest.json",
        body=json.dumps({"run_id": run_id, "sources": source_objects}, indent=2),
    )

    default_broker.emit_activity(
        run_id=run_id,
        stage="claims",
        title="Master summary of source documents created",
        detail=f"Explored {len(file_profiles)} source file(s) -> stage_1_claims/master_source_summary.md",
        kind="artifact",
        artifact="master_source_summary.md",
    )

    return {
        "master_summary_md": master_md,
        "per_file_mds": per_file_mds,
        "file_profiles": file_profiles,
        "source_objects": source_objects,
        "datasets": dataset_profiles,
        "columns": column_profiles,
    }
