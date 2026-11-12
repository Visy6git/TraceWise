"""Claims Registry API router."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.harness.paths import strip_extended_prefix, to_extended_path
from app.schemas.claim import ClaimPatch
from app.services.database import default_claim_repo, default_run_repo
from app.services.storage import default_storage

router = APIRouter(tags=["claims"])

# Defensive cap on rows returned per table, independent of what the agent wrote.
_MAX_ROWS_PER_TABLE = 500
# In-UI preview of a full raw source sheet: bounded so the browser can render it.
# The complete sheet is available via the CSV download endpoint.
_DEFAULT_SHEET_PREVIEW = 500
_MAX_SHEET_PREVIEW = 2000
# Hard cap when materializing a sheet to CSV, to avoid unbounded memory use.
_MAX_CSV_ROWS = 100_000


def _normalize_table(table: Any) -> dict[str, Any] | None:
    """Coerce an agent-written parent/child data table into a safe, bounded shape."""
    if not isinstance(table, dict):
        return None
    rows = table.get("rows")
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    columns = table.get("columns")
    if not (isinstance(columns, list) and columns):
        seen: dict[str, None] = {}
        for r in rows:
            for k in r.keys():
                seen.setdefault(str(k), None)
        columns = list(seen.keys())
    columns = [str(c) for c in columns]
    full_count = table.get("row_count")
    full_count = int(full_count) if isinstance(full_count, (int, float)) else len(rows)
    truncated = bool(table.get("truncated")) or len(rows) > _MAX_ROWS_PER_TABLE or full_count > len(rows)
    return {
        "label": str(table.get("label") or ""),
        "source_file": table.get("source_file"),
        "sheet": table.get("sheet"),
        "row_count": full_count,
        "columns": columns,
        "rows": rows[:_MAX_ROWS_PER_TABLE],
        "truncated": truncated,
    }


@router.get("/runs/{run_id}/stage-1/claims", response_model=list[dict[str, Any]])
def list_claims(run_id: str) -> list[dict[str, Any]]:
    claims = default_claim_repo.list_claims(run_id)
    return claims


def _read_sheet_df(physical_path: str, sheet: str | None, header_row: int):
    """Read a source sheet into a cleaned DataFrame of strings (or None if unreadable)."""
    import pandas as pd

    name = Path(physical_path).name
    p = to_extended_path(strip_extended_prefix(Path(physical_path)).resolve())
    if not p.exists():
        return None
    if name.lower().endswith(".csv"):
        df = pd.read_csv(p, skiprows=header_row, dtype=str)
    else:
        df = pd.read_excel(p, sheet_name=sheet, skiprows=header_row, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    return df.dropna(how="all")


def _read_full_sheet(
    physical_path: str, sheet: str | None, header_row: int, limit: int, offset: int
) -> dict[str, Any] | None:
    """Read a bounded preview window (limit/offset) of a source sheet for the UI."""
    import pandas as pd

    name = Path(physical_path).name
    sheet_label = None if name.lower().endswith(".csv") else sheet
    try:
        df = _read_sheet_df(physical_path, sheet, header_row)
    except Exception as exc:  # noqa: BLE001 - surface a readable error to the UI
        return {
            "source_file": name,
            "sheet": sheet_label,
            "header_row_index": header_row,
            "error": f"Could not read sheet: {exc}",
            "row_count": 0,
            "columns": [],
            "rows": [],
            "offset": offset,
            "truncated": False,
        }
    if df is None:
        return None

    total = int(len(df))
    window = df.iloc[offset: offset + limit]
    columns = [str(c) for c in window.columns]
    rows = [
        {str(k): (None if pd.isna(v) else v) for k, v in rec.items()}
        for rec in window.to_dict(orient="records")
    ]
    return {
        "source_file": name,
        "sheet": sheet_label,
        "header_row_index": header_row,
        "row_count": total,
        "columns": columns,
        "rows": rows,
        "offset": offset,
        "truncated": offset > 0 or (offset + len(rows)) < total,
    }


def _resolve_claim_sheet_specs(run_id: str, claim: dict[str, Any], run: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve the ordered (file, sheet, header_row) data-sheet specs mapped to a claim."""
    source_paths: list[str] = run.get("source_object_ids") or []
    mapped = claim.get("source_document_mapped") or []
    if mapped:
        files = [s for s in source_paths if Path(s).name in mapped] or source_paths
    else:
        files = source_paths

    sk_datasets: list[dict[str, Any]] = []
    try:
        sk = json.loads(default_storage.read_text(f"default/{run_id}/stage_1_claims/source_knowledge.json"))
        sk_datasets = sk.get("datasets") or []
    except Exception:
        pass

    specs: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for sp in files:
        name = Path(sp).name
        datasets = [d for d in sk_datasets if d.get("source_filename") == name and d.get("is_data", True)]
        if not datasets:
            datasets = [{"sheet_or_table": None, "header_row": 0}]
        for d in datasets:
            sheet = d.get("sheet_or_table")
            key = (name, sheet)
            if key in seen:
                continue
            seen.add(key)
            specs.append({"path": sp, "sheet": sheet, "header_row": int(d.get("header_row") or 0)})
    return specs


@router.get("/runs/{run_id}/claims/{claim_id}/source-data", response_model=dict[str, Any])
def get_claim_source_data(
    run_id: str,
    claim_id: str,
    limit: int = Query(_DEFAULT_SHEET_PREVIEW, ge=1, le=_MAX_SHEET_PREVIEW),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Return a bounded preview of the mapped source Excel/CSV sheet(s) for a claim.

    The browser cannot render tens of thousands of rows, so this returns a window
    (limit/offset) with the true `row_count`; the complete sheet is available via the
    `/source-data.csv` download for manual inspection in Excel.
    """
    run = default_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    claim = default_claim_repo.get_claim(run_id, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")

    specs = _resolve_claim_sheet_specs(run_id, claim, run)
    sheets_out: list[dict[str, Any]] = []
    for spec in specs:
        table = _read_full_sheet(spec["path"], spec["sheet"], spec["header_row"], limit, offset)
        if table is not None:
            sheets_out.append(table)

    if not sheets_out:
        raise HTTPException(
            status_code=404,
            detail=f"No readable source sheet is mapped to claim {claim_id}",
        )

    return {"run_id": run_id, "claim_id": claim_id, "limit": limit, "offset": offset, "sheets": sheets_out}


@router.get("/runs/{run_id}/claims/{claim_id}/source-data.csv")
def get_claim_source_csv(
    run_id: str,
    claim_id: str,
    file: str = Query(..., description="Mapped source filename to export"),
    sheet: str | None = Query(None, description="Sheet name within the file"),
) -> Response:
    """Download one complete mapped source sheet as CSV, for manual inspection in Excel."""
    run = default_run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    claim = default_claim_repo.get_claim(run_id, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")

    specs = _resolve_claim_sheet_specs(run_id, claim, run)
    match = next(
        (s for s in specs if Path(s["path"]).name == file and (sheet is None or s["sheet"] == sheet)),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail=f"Sheet not mapped to claim {claim_id}: {file} / {sheet}")

    try:
        df = _read_sheet_df(match["path"], match["sheet"], match["header_row"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not read sheet: {exc}") from exc
    if df is None:
        raise HTTPException(status_code=404, detail="Source file not found on disk")

    csv_text = df.head(_MAX_CSV_ROWS).to_csv(index=False)
    safe_sheet = (match["sheet"] or "sheet").replace(" ", "_").replace("/", "-")
    filename = f"{claim_id}_{safe_sheet}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/runs/{run_id}/claims/{claim_id}/data", response_model=dict[str, Any])
def get_claim_data(run_id: str, claim_id: str) -> dict[str, Any]:
    """Return the actual source rows backing the parent and each child claim (Stage 2).

    Reads the `claim_data.json` the rules agent produced for this claim and returns a
    bounded, normalized shape the UI can render as tables.
    """
    try:
        raw = default_storage.read_text(
            f"default/{run_id}/stage_2_rules/claims/{claim_id}/claim_data.json"
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"No verified data available for claim {claim_id}; run or rerun Stage 2 first",
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="claim_data.json is not valid JSON") from exc

    parent = _normalize_table(parsed.get("parent"))
    children_raw = parsed.get("children")
    children = []
    if isinstance(children_raw, list):
        for ch in children_raw:
            norm = _normalize_table(ch)
            if norm is not None:
                norm["child_claim_id"] = str(ch.get("child_claim_id") or "") if isinstance(ch, dict) else ""
                children.append(norm)

    return {
        "run_id": run_id,
        "claim_id": claim_id,
        "parent": parent,
        "children": children,
    }


@router.patch("/runs/{run_id}/stage-1/claims/{claim_id}", response_model=dict[str, Any])
def update_claim(run_id: str, claim_id: str, patch: ClaimPatch) -> dict[str, Any]:
    try:
        updated = default_claim_repo.update_claim_patch(
            run_id=run_id,
            claim_id=claim_id,
            expected_version=patch.expected_version,
            patch=patch.model_dump(exclude_unset=True),
            reviewer_reason=patch.reviewer_reason,
            actor_id="reviewer",
        )
        return updated
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
