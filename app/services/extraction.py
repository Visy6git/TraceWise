"""Document and workbook extraction adapters.

Extracts canonical document blocks, tables, locators, and workbook profiles
from DOCX, PDF, and XLSX sources with stable locators and checksums.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

import docx
import openpyxl


def extract_target_report(file_path: str | Path) -> dict[str, Any]:
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Target document not found at {file_path}")

    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    doc = docx.Document(str(path))
    blocks: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []

    current_section_id: str | None = None
    current_section_num: str | None = None
    current_section_title: str | None = None

    # Helper to recognize section headers (e.g., "5.1 Cumulative Subject Exposure...", "Section 16.3 ...", etc.)
    section_regex = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$")

    block_seq = 0
    for p_idx, p in enumerate(doc.paragraphs):
        text = p.text.strip()
        if not text:
            continue

        block_seq += 1
        block_id = f"blk_{block_seq:04d}"

        # Check if paragraph is a section header
        match = section_regex.match(text)
        if match:
            current_section_num = match.group(1)
            current_section_title = match.group(2).strip()
            current_section_id = f"sec_{current_section_num.replace('.', '_')}"

            level = len(current_section_num.split(".")) - 1
            parent_id = None
            if "." in current_section_num:
                parent_parts = current_section_num.split(".")[:-1]
                parent_id = f"sec_{'_'.join(parent_parts)}"

            sections.append({
                "section_id": current_section_id,
                "number": current_section_num,
                "title": current_section_title,
                "level": level,
                "parent_id": parent_id,
                "is_leaf": True,  # updated later if children exist
                "extraction_status": "extracted",
                "locators": [{
                    "document_id": path.name,
                    "block_id": block_id,
                    "paragraph_index": p_idx,
                }],
            })

        blocks.append({
            "block_id": block_id,
            "type": "paragraph",
            "section_id": current_section_id or "sec_preamble",
            "section_number": current_section_num or "0",
            "text": text,
            "paragraph_index": p_idx,
            "locator": {
                "document_id": path.name,
                "block_id": block_id,
                "paragraph_index": p_idx,
            },
        })

    # Update parent/children relationships
    sec_ids = {s["section_id"]: s for s in sections}
    for s in sections:
        if s["parent_id"] and s["parent_id"] in sec_ids:
            sec_ids[s["parent_id"]]["is_leaf"] = False

    # Extract tables
    for t_idx, table in enumerate(doc.tables):
        block_seq += 1
        block_id = f"blk_tbl_{block_seq:04d}"

        grid: list[list[str]] = []
        for r_idx, row in enumerate(table.rows):
            row_cells = [cell.text.strip() for cell in row.cells]
            grid.append(row_cells)

        headers = grid[0] if grid else []
        data_rows = grid[1:] if len(grid) > 1 else []

        blocks.append({
            "block_id": block_id,
            "type": "table",
            "section_id": current_section_id or "sec_tables",
            "section_number": current_section_num or "0",
            "headers": headers,
            "rows": data_rows,
            "table_index": t_idx,
            "locator": {
                "document_id": path.name,
                "block_id": block_id,
                "table_index": t_idx,
            },
        })

    return {
        "filename": path.name,
        "sha256": sha256,
        "size_bytes": path.stat().st_size,
        "blocks": blocks,
        "sections": sections,
    }


def extract_source_file(file_path: str | Path) -> dict[str, Any]:
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Source file not found at {file_path}")

    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    suffix = path.suffix.lower()

    datasets: list[dict[str, Any]] = []

    if suffix in (".xlsx", ".xlsm", ".xltx"):
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        try:
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                raw_rows = list(ws.iter_rows(values_only=True))
                if not raw_rows:
                    continue

                # Header detection: first row with non-empty strings
                header_idx = 0
                for idx, r in enumerate(raw_rows):
                    non_empty = [c for c in r if c is not None and str(c).strip()]
                    if non_empty:
                        header_idx = idx
                        break

                header_row = [str(c).strip() if c is not None else f"col_{i}" for i, c in enumerate(raw_rows[header_idx])]
                data_rows = raw_rows[header_idx + 1:]

                dataset_id = f"{path.stem}_{sheet_name}".replace(" ", "_")

                datasets.append({
                    "dataset_id": dataset_id,
                    "sheet_or_table": sheet_name,
                    "header_row_index": header_idx,
                    "columns": header_row,
                    "row_count": len(data_rows),
                    "sample_rows": [list(r) for r in data_rows[:10]],
                    "visible": True,
                })
        finally:
            wb.close()

    elif suffix == ".csv":
        import csv
        with open(str(path), "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            all_rows = list(reader)
            if all_rows:
                headers = all_rows[0]
                data_rows = all_rows[1:]
                datasets.append({
                    "dataset_id": path.stem,
                    "sheet_or_table": path.name,
                    "header_row_index": 0,
                    "columns": headers,
                    "row_count": len(data_rows),
                    "sample_rows": data_rows[:10],
                    "visible": True,
                })

    return {
        "source_id": path.stem,
        "filename": path.name,
        "sha256": sha256,
        "size_bytes": path.stat().st_size,
        "format": suffix.lstrip("."),
        "datasets": datasets,
    }
