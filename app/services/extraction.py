"""Document and workbook extraction adapters.

Extracts canonical document blocks, tables, locators, and workbook profiles
from DOCX, PDF, and XLSX sources with stable locators and checksums.

Section detection is style-aware. Regulated PBRER/CSMR reports number their
headings with Word *autonumbering* driven by paragraph styles (e.g.
``CS 1ST LEVEL autono`` ... ``CS 5th level autono``). The computed number
(``16.3``) is therefore NOT present in the paragraph text — it must be
reconstructed by walking the heading styles in document order and keeping a
counter per level. A naive ``^\\d+`` regex misfires on ordinary sentences that
begin with a number, which is why earlier extraction produced garbage sections.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterator

import docx
import openpyxl
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

# Autonumbered heading styles: "CS 1ST LEVEL autono", "CS 3rd level autono", ...
_AUTONO_STYLE_RE = re.compile(r"\bcs\s+(\d+)(?:st|nd|rd|th)\s+level\s+autono\b", re.I)
# Standard Word heading styles as a fallback: "Heading 1", "Heading 2", ...
_STD_HEADING_RE = re.compile(r"^heading\s+(\d+)$", re.I)


def _heading_level(paragraph: Paragraph) -> int | None:
    """Return the 1-based outline level of a heading paragraph, else None.

    Relies on the paragraph *style* rather than the text, because the heading
    number is produced by Word autonumbering and is absent from ``.text``.
    """
    style_name = ""
    try:
        style_name = paragraph.style.name or ""
    except Exception:
        style_name = ""
    m = _AUTONO_STYLE_RE.search(style_name)
    if m:
        return int(m.group(1))
    m = _STD_HEADING_RE.match(style_name.strip())
    if m:
        return int(m.group(1))
    return None


def _iter_block_items(document: Any) -> Iterator[tuple[str, Any]]:
    """Yield paragraphs and tables in true document order.

    ``doc.paragraphs`` and ``doc.tables`` are separate collections that lose
    interleaving; walking the body XML preserves the real order so a table is
    attributed to the section it actually appears under.
    """
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield "paragraph", Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield "table", Table(child, document)


def _advance_number(counters: list[int], level: int) -> str:
    """Advance the hierarchical heading counter to ``level`` and return the number."""
    while len(counters) < level:
        counters.append(0)
    del counters[level:]
    counters[level - 1] += 1
    return ".".join(str(c) for c in counters[:level])


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

    counters: list[int] = []
    block_seq = 0
    para_seq = 0
    table_seq = 0

    for kind, item in _iter_block_items(doc):
        if kind == "paragraph":
            text = item.text.strip()
            para_index = para_seq
            para_seq += 1
            if not text:
                continue

            block_seq += 1
            block_id = f"blk_{block_seq:04d}"

            level = _heading_level(item)
            is_heading = level is not None
            if is_heading:
                number = _advance_number(counters, level)
                current_section_num = number
                current_section_id = f"sec_{number.replace('.', '_')}"
                parent_id = None
                if "." in number:
                    parent_id = f"sec_{number.rsplit('.', 1)[0].replace('.', '_')}"
                sections.append({
                    "section_id": current_section_id,
                    "number": number,
                    "title": text,
                    "level": level - 1,
                    "parent_id": parent_id,
                    "is_leaf": True,
                    "extraction_status": "extracted",
                    "locators": [{
                        "document_id": path.name,
                        "block_id": block_id,
                        "paragraph_index": para_index,
                    }],
                })

            blocks.append({
                "block_id": block_id,
                "type": "heading" if is_heading else "paragraph",
                "section_id": current_section_id or "sec_preamble",
                "section_number": current_section_num or "",
                "is_heading": is_heading,
                "heading_level": (level - 1) if is_heading else None,
                "text": text,
                "paragraph_index": para_index,
                "locator": {
                    "document_id": path.name,
                    "block_id": block_id,
                    "paragraph_index": para_index,
                },
            })

        else:  # table
            table = item
            block_seq += 1
            t_idx = table_seq
            table_seq += 1
            block_id = f"blk_tbl_{block_seq:04d}"

            grid: list[list[str]] = []
            for row in table.rows:
                grid.append([cell.text.strip() for cell in row.cells])

            headers = grid[0] if grid else []
            data_rows = grid[1:] if len(grid) > 1 else []

            blocks.append({
                "block_id": block_id,
                "type": "table",
                "section_id": current_section_id or "sec_preamble",
                "section_number": current_section_num or "",
                "is_heading": False,
                "headers": headers,
                "rows": data_rows,
                "table_index": t_idx,
                "locator": {
                    "document_id": path.name,
                    "block_id": block_id,
                    "table_index": t_idx,
                },
            })

    # Update parent/children relationships (is_leaf = no child references it).
    sec_ids = {s["section_id"]: s for s in sections}
    for s in sections:
        if s["parent_id"] and s["parent_id"] in sec_ids:
            sec_ids[s["parent_id"]]["is_leaf"] = False

    return {
        "filename": path.name,
        "sha256": sha256,
        "size_bytes": path.stat().st_size,
        "blocks": blocks,
        "sections": sections,
    }


_HEADER_SCAN_ROWS = 40


def _detect_header(scan: list[tuple], max_col: int) -> tuple[int, list[str] | None, list[str]]:
    """Locate the real header row among buffered rows.

    Returns (header_row_index, header_names, preamble_lines). The header is the
    first row that fills most of the columns — this skips sparse banner/preamble
    rows that precede the table in regulated exports. header_names is None when
    the sheet has no tabular content at all.
    """
    def width(row: tuple) -> int:
        return sum(1 for c in row if c is not None and str(c).strip())

    widths = [width(r) for r in scan]
    if not widths or max(widths) == 0:
        return 0, None, []

    expected = max(max_col, max(widths))
    threshold = max(3, int(0.6 * expected))

    header_idx: int | None = next((i for i, w in enumerate(widths) if w >= threshold), None)
    if header_idx is None:
        # No wide row (e.g. a cover page): fall back to the first non-empty row.
        header_idx = next((i for i, w in enumerate(widths) if w > 0), None)
    if header_idx is None:
        return 0, None, []

    header_row: list[str] = []
    seen: dict[str, int] = {}
    for i, c in enumerate(scan[header_idx]):
        name = str(c).strip() if c is not None and str(c).strip() else f"col_{i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}__{seen[name]}"
        else:
            seen[name] = 0
        header_row.append(name)

    preamble: list[str] = []
    for r in scan[:header_idx]:
        line = next((str(c).strip() for c in r if c is not None and str(c).strip()), None)
        if line:
            preamble.append(line)
    return header_idx, header_row, preamble


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
                dataset_id = f"{path.stem}_{sheet_name}".replace(" ", "_")
                try:
                    max_col = ws.max_column if isinstance(ws.max_column, int) else 0
                    max_row = ws.max_row if isinstance(ws.max_row, int) else None
                except Exception:
                    max_col, max_row = 0, None

                # Buffer the first rows to locate the real header. Regulated
                # exports (CSMR) begin with a sparse banner/preamble ("Creation
                # Date…", "Count of Cases…"); the real header is the first row
                # that fills most columns, not merely the first non-empty row.
                scan: list[tuple] = []
                stream = ws.iter_rows(values_only=True)
                for r in stream:
                    scan.append(r)
                    if len(scan) >= _HEADER_SCAN_ROWS:
                        break

                header_idx, header_row, preamble = _detect_header(scan, max_col)
                if header_row is None:
                    continue  # no usable tabular content on this sheet

                sample_rows: list[list[Any]] = []
                buffered_data = scan[header_idx + 1:]
                for r in buffered_data:
                    if len(sample_rows) >= 10:
                        break
                    if any(c is not None and str(c).strip() for c in r):
                        sample_rows.append(list(r))

                if max_row is not None:
                    data_count = max(max_row - (header_idx + 1), 0)
                else:
                    data_count = sum(
                        1 for r in buffered_data if any(c is not None and str(c).strip() for c in r)
                    )
                    for r in stream:
                        if any(c is not None and str(c).strip() for c in r):
                            data_count += 1

                real_cols = sum(1 for c in header_row if not c.startswith("col_"))
                is_data = (
                    real_cols >= 2
                    and data_count > 0
                    and not sheet_name.lower().startswith("cover")
                )

                datasets.append({
                    "dataset_id": dataset_id,
                    "sheet_or_table": sheet_name,
                    "header_row_index": header_idx,
                    "columns": header_row,
                    "row_count": data_count,
                    "sample_rows": sample_rows,
                    "preamble": preamble,
                    "is_data": is_data,
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
                max_col = max((len(r) for r in all_rows[:_HEADER_SCAN_ROWS]), default=0)
                header_idx, header_row, preamble = _detect_header(
                    [tuple(r) for r in all_rows[:_HEADER_SCAN_ROWS]], max_col
                )
                if header_row is None:
                    header_idx, header_row, preamble = 0, all_rows[0], []
                data_rows = all_rows[header_idx + 1:]
                datasets.append({
                    "dataset_id": path.stem,
                    "sheet_or_table": path.name,
                    "header_row_index": header_idx,
                    "columns": header_row,
                    "row_count": len(data_rows),
                    "sample_rows": data_rows[:10],
                    "preamble": preamble,
                    "is_data": len(header_row) >= 2 and len(data_rows) > 0,
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
