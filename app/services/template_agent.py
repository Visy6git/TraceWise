from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pydantic import BaseModel, Field, field_validator

try:
    from strands import tool as strands_tool
except ImportError:  # pragma: no cover - fallback when strands-agents is not installed
    def strands_tool(fn):
        return fn

from app.services.llm_client import invoke_tool_call, llm_status_info

AguiEmitter = Callable[[str, dict[str, Any]], None]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _norm(text: str) -> str:
    return _clean(text).casefold().strip(" :–-\t")


def _slug_key(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s[:64] or "custom_field"


def _emit_agui(emitter: AguiEmitter | None, event_type: str, **payload: Any) -> None:
    if emitter:
        emitter(event_type, {"timestamp": _utcnow(), **payload})


# ==================== STRUCTURED TOOL INPUT MODELS ====================
class BlueprintFieldSpec(BaseModel):
    field_label: str = Field(..., description="FIELD LABEL observed in the document table")
    key: str = Field(..., description="Normalized snake_case KEY for this field")
    type: str = Field(..., description="Semantic TYPE inferred from the document table")
    generic_placeholder: str = Field(
        ...,
        description="GENERIC PLACEHOLDER token (e.g. {{...}}) representing dynamic values — never previous-period numbers or narratives",
    )
    source_intent: str = Field(
        ...,
        description="SOURCE INTENT describing what source data or reviewer input populates this field",
    )
    required: bool = Field(default=True, description="Whether this field is required in the table")
    row_index: int | None = Field(default=None, description="0-based unified row index where this field's value sits")
    cell_index: int | None = Field(default=None, description="0-based cell index in that row where the value sits")
    paragraph_index: int = Field(default=0, description="0-based paragraph index inside the value cell")


def _coerce_str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                s = s[1:-1].strip()
        if not s:
            return []
        parts = [p.strip(" '\"‘’") for p in re.split(r";|\n|,(?=\s*[A-Z'\"‘])", s) if p.strip(" '\"‘’")]
        return parts or [s]
    return [str(v).strip()]


class BlueprintTableSpec(BaseModel):
    table_id: str = Field(..., description="Exact table_id from the Section 16.3 input")
    topic_heading: str = Field(..., description="Topic heading / title for this table")
    criterion_type: str = Field(
        default="manual",
        description="Search criterion family if present (e.g. MedDRA PT, MedDRA HLT, MedDRA SMQ, or manual)",
    )
    criterion_terms: list[str] = Field(default_factory=list, description="Explicit search terms listed in this table, if any")
    requires_reporting_interval: bool = Field(default=False, description="True if the table states counts for a reporting interval")
    requires_initial_only: bool = Field(default=False, description="True if the table explicitly counts initial cases")
    fields: list[BlueprintFieldSpec] = Field(default_factory=list, description="Ordered list of generic fields mapped from this table")

    @field_validator("criterion_terms", mode="before")
    @classmethod
    def _v_criterion_terms(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)

    @field_validator("fields", mode="before")
    @classmethod
    def _v_fields(cls, v: Any) -> list[Any]:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                return []
        return v or []


class ReferenceTableSummary(BaseModel):
    table_id: str = Field(..., description="table_id of the chosen reference table")
    topic_heading: str = Field(..., description="Topic heading of the chosen reference table")
    why_selected: str = Field(..., description="Why this table is one of the 2 best reference examples")
    structure_summary: str = Field(..., description="Concise summary of rows, structure, counts, criteria and narrative blocks")
    example_fields: list[str] = Field(default_factory=list, description="Representative FIELD LABEL -> {{placeholder}} highlights")

    @field_validator("example_fields", mode="before")
    @classmethod
    def _v_example_fields(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)


class MasterMarkdownResponse(BaseModel):
    master_md: str = Field(
        ...,
        description="Complete client-specific master.md Markdown guide for Section 16.3 tables, layout conventions, variations and guardrails",
    )
    reference_summaries: list[ReferenceTableSummary] = Field(
        ...,
        min_length=1,
        max_length=2,
        description="The 2 best representative table summaries to attach as reference examples (or 1 if only 1 table exists)",
    )

    @field_validator("reference_summaries", mode="before")
    @classmethod
    def _v_ref_summaries(cls, v: Any) -> list[Any]:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                return []
        return v or []


# ==================== STRANDS STRUCTURED PYTHON TOOLS ====================
@strands_tool
def register_table_blueprint(
    table_id: str,
    topic_heading: str,
    fields: list[dict[str, Any]],
    criterion_type: str = "manual",
    criterion_terms: list[str] | None = None,
    requires_reporting_interval: bool = False,
    requires_initial_only: bool = False,
) -> dict[str, Any]:
    """Register the structured Generic Table Blueprint for a single Section 16.3 table.

    Each item in `fields` must specify FIELD LABEL (`field_label`), KEY (`key`),
    TYPE (`type`), GENERIC PLACEHOLDER (`generic_placeholder`), and SOURCE INTENT (`source_intent`).
    """
    validated = BlueprintTableSpec(
        table_id=table_id,
        topic_heading=topic_heading,
        fields=[BlueprintFieldSpec.model_validate(f) for f in (fields or [])],
        criterion_type=criterion_type or "manual",
        criterion_terms=list(criterion_terms or []),
        requires_reporting_interval=bool(requires_reporting_interval),
        requires_initial_only=bool(requires_initial_only),
    )
    return validated.model_dump()


@strands_tool
def publish_master_knowledge(
    master_md: str,
    reference_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Publish client-specific master.md documentation and attach the 2 best reference table summaries."""
    validated = MasterMarkdownResponse(
        master_md=master_md,
        reference_summaries=[ReferenceTableSummary.model_validate(s) for s in (reference_summaries or [])[:2]],
    )
    md = validated.master_md.strip()
    summaries = validated.reference_summaries[:2]
    if summaries and "best reference table summaries" not in md.lower():
        md = md + "\n" + _format_reference_summaries_markdown(summaries)
    return {
        "master_md": md,
        "reference_summaries": [s.model_dump() for s in summaries],
    }


# ==================== STEP 1: DETERMINISTIC SECTION 16.3 READER ====================
def _extract_raw_table(table: Table, table_index: int, source_file: str, topic_heading: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for ri, row in enumerate(table.rows):
        cells: list[dict[str, Any]] = []
        seen_tc: set[int] = set()
        for ci, cell in enumerate(row.cells):
            tc_id = id(cell._tc)
            if tc_id in seen_tc:
                continue
            seen_tc.add(tc_id)
            tc_pr = cell._tc.tcPr
            span = 1
            vmerge = None
            try:
                if tc_pr is not None and tc_pr.gridSpan is not None:
                    span = int(tc_pr.gridSpan.val)
                if tc_pr is not None and tc_pr.vMerge is not None:
                    vmerge = tc_pr.vMerge.val or "continue"
            except Exception:
                pass
            paragraphs = [_clean(p.text) for p in cell.paragraphs]
            non_empty = [p for p in paragraphs if p]
            cells.append({
                "cell_index": ci,
                "grid_span": span,
                "vertical_merge": vmerge,
                "paragraph_count": len(paragraphs),
                "paragraphs": paragraphs,
                "text": _clean(" ".join(non_empty)),
            })
        rows.append({
            "row_index": ri,
            "physical_docx_table_index": table_index,
            "physical_row_index": ri,
            "cells": cells,
        })

    style = table.style.name if table.style else ""
    col_widths: list[int] = []
    try:
        col_widths = [int(c.get(qn("w:w"))) for c in table._tbl.tblGrid.gridCol_lst]
    except Exception:
        pass
    try:
        autofit = bool(table.autofit)
    except Exception:
        autofit = None

    return {
        "table_id": f"{Path(source_file).stem}-table-{table_index}",
        "source_file": source_file,
        "docx_table_index": table_index,
        "merged_docx_indices": [table_index],
        "topic_heading": topic_heading or f"Section 16.3 Table {table_index}",
        "table_style": style,
        "column_count": len(table.columns),
        "column_widths_dxa": col_widths,
        "row_count": len(table.rows),
        "autofit": autofit,
        "raw_rows": rows,
        "continuation_of_previous": False,
    }


def _looks_like_continuation(raw_table: dict[str, Any], previous_table: dict[str, Any] | None) -> bool:
    if not previous_table:
        return False
    rows = raw_table.get("raw_rows") or []
    if not rows or not rows[0].get("cells"):
        return False
    first_cell_text = _norm(rows[0]["cells"][0].get("text", ""))
    same_heading = _norm(raw_table.get("topic_heading", "")) == _norm(previous_table.get("topic_heading", ""))
    has_cont_marker = any(tok in first_cell_text for tok in ["cont’d", "cont'd", "continued", "(cont"])
    if has_cont_marker:
        return True
    prev_first_span = (previous_table.get("raw_rows") or [{}])[0].get("cells", [{}])[0].get("grid_span", 1)
    curr_first_span = rows[0]["cells"][0].get("grid_span", 1)
    if same_heading and prev_first_span > 1 and curr_first_span == 1:
        return True
    return False


def _merge_continuation_into_parent(parent: dict[str, Any], cont: dict[str, Any]) -> None:
    offset = len(parent["raw_rows"])
    for idx, row in enumerate(cont.get("raw_rows") or []):
        parent["raw_rows"].append({**row, "row_index": offset + idx})
    parent["row_count"] = len(parent["raw_rows"])
    parent["column_count"] = max(int(parent.get("column_count", 0)), int(cont.get("column_count", 0)))
    if cont["docx_table_index"] not in parent["merged_docx_indices"]:
        parent["merged_docx_indices"].append(cont["docx_table_index"])


def extract_raw_section_16_3(path: Path) -> dict[str, Any]:
    """Deterministically isolate Section 16.3 paragraphs and raw Word tables (with continuations folded into parent)."""
    doc = Document(path)
    in_section = False
    seen_section = False
    current_heading = ""
    table_index = 0
    raw_tables: list[dict[str, Any]] = []
    section_intro: list[str] = []

    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, doc)
            txt = _clean(para.text)
            n = _norm(txt)
            style = (para.style.name if para.style else "") or ""
            low_style = style.lower()

            heading_clean = re.sub(r"^16\.3\s*", "", n)
            is_heading_style = any(k in low_style for k in ["heading", "level", "title"])
            is_toc = "toc" in low_style

            if not in_section:
                # Require a real heading style (prevents matching plain body/TOC cross-references earlier in the doc)
                if (
                    is_heading_style
                    and not is_toc
                    and (
                        heading_clean == "evaluation of risks and new information"
                        or re.match(r"^16\.3(?:\s|$)", n)
                    )
                ):
                    in_section = True
                    seen_section = True
                    current_heading = txt
                    continue
            else:
                stop_clean = re.sub(r"^16\.4\s*", "", n)
                is_next_major = bool(re.match(r"^(?:16\.[4-9]|1[7-9]\.|2\d\.)\s*", n))
                if (
                    is_heading_style
                    and not is_toc
                    and (
                        stop_clean in {
                            "important identified risks",
                            "important potential risks",
                            "characterisation of risks",
                            "characterization of risks",
                        }
                        or is_next_major
                    )
                ):
                    in_section = False
                    continue

                if txt:
                    if any(k in low_style for k in ["3rd level", "4th level", "heading 2", "heading 3", "heading 4"]):
                        current_heading = txt
                    elif not raw_tables and len(section_intro) < 6 and len(txt) > 15:
                        section_intro.append(txt[:500])

        elif child.tag == qn("w:tbl"):
            if in_section:
                table_obj = next((t for t in doc.tables if t._tbl is child), None)
                if table_obj is not None:
                    raw = _extract_raw_table(table_obj, table_index, path.name, current_heading)
                    non_empty_text = " ".join(c["text"] for r in raw["raw_rows"] for c in r["cells"]).strip()
                    if non_empty_text:
                        if raw_tables and _looks_like_continuation(raw, raw_tables[-1]):
                            _merge_continuation_into_parent(raw_tables[-1], raw)
                        else:
                            raw["section"] = "16.3"
                            raw_tables.append(raw)
            table_index += 1

    # Fallback if a tenant document uses a non-standard Section 16.3 heading
    if not seen_section and not raw_tables:
        for idx, table_obj in enumerate(doc.tables):
            raw = _extract_raw_table(table_obj, idx, path.name, f"Detected Table {idx + 1}")
            non_empty_text = " ".join(c["text"] for r in raw["raw_rows"] for c in r["cells"]).strip()
            if non_empty_text and len(raw["raw_rows"]) >= 2:
                if raw_tables and _looks_like_continuation(raw, raw_tables[-1]):
                    _merge_continuation_into_parent(raw_tables[-1], raw)
                else:
                    raw["section"] = "inferred-16.3"
                    raw_tables.append(raw)

    return {
        "filename": path.name,
        "paragraph_count": len(doc.paragraphs),
        "table_count": len(doc.tables),
        "section_16_3_found": seen_section,
        "section_intro": section_intro,
        "tables": raw_tables,
        "styles": sorted({t["table_style"] for t in raw_tables if t.get("table_style")}),
        "warning": None if seen_section else "Section 16.3 heading was not explicitly matched; structural fallback was used.",
    }


def _compact_table_for_llm(raw_table: dict[str, Any], preserve_full_criteria: bool = False) -> dict[str, Any]:
    """Build a crisp, token-efficient representation of ONE Section 16.3 table for tool calling.
    Preserves full verbatim MedDRA/Search Criteria text so product templates never truncate terminologies.
    """
    compact_rows = []
    for row in raw_table.get("raw_rows") or []:
        row_text_low = " ".join((c.get("text") or "") for c in (row.get("cells") or [])).lower()
        is_criteria_row = any(tok in row_text_low for tok in ("search criteria", "meddra", "smq", "hlt", "preferred term"))
        char_cap = 1600 if (preserve_full_criteria or is_criteria_row) else 180
        para_cap = 12 if (preserve_full_criteria or is_criteria_row) else 5

        compact_cells = []
        for cell in row.get("cells") or []:
            paras = [
                (p[:char_cap] + ("…" if len(p) > char_cap else ""))
                for p in (cell.get("paragraphs") or [])
                if p
            ]
            compact_cells.append({
                "cell_index": cell["cell_index"],
                "grid_span": cell.get("grid_span", 1),
                "paragraphs": paras[:para_cap],
            })
        compact_rows.append({
            "row_index": row["row_index"],
            "cells": compact_cells,
        })
    return {
        "table_id": raw_table["table_id"],
        "source_file": raw_table["source_file"],
        "topic_heading": raw_table["topic_heading"],
        "row_count": raw_table["row_count"],
        "column_count": raw_table["column_count"],
        "table_style": raw_table.get("table_style", ""),
        "rows": compact_rows,
    }


# ==================== STEP 2: TABLE-BY-TABLE STRANDS TOOL BLUEPRINT AGENT ====================
SINGLE_TABLE_TOOL_SYSTEM_PROMPT = """You are a Document Table Blueprint Agent analyzing ONE Section 16.3 table from a client PBRER document.
You MUST call the `register_table_blueprint` tool to submit ALL unique fields present in this table. Do not reply with plain prose.

For EVERY distinct row/field present in this table, populate these 5 structured columns:
- FIELD LABEL (`field_label`): clean generic row label WITHOUT old-period values, numbers, or trailing colons
- KEY (`key`): unique normalized snake_case identifier for that field within this table
- TYPE (`type`): semantic field type inferred from the table (e.g. count_ratio, count, criteria, narrative, source_note, date, percentage)
- GENERIC PLACEHOLDER (`generic_placeholder`): a descriptive token using the field's meaning, wrapped in double braces (NEVER write literal "{{...}}")
- SOURCE INTENT (`source_intent`): concise description of what source data or reviewer input populates this field

CRITICAL RULES:
1. Use the exact `table_id` provided in the input.
2. ONE FIELD PER CONCEPTUAL ROW — NEVER emit two separate fields for `cell_index: 0` (the label cell) and `cell_index: 1` (the value cell) of the same row! Combine each label+value row into ONE field whose `field_label` comes from cell 0 and whose `cell_index` points to cell 1 (the value cell).
3. NEVER duplicate keys within a table. If a field continues onto a subsequent row (e.g. "(cont'd)"), keep ONE single field entry for that key rather than repeating it.
4. Map EVERY distinct labeled row/field in the table (including merged cells that stack two labels vertically). Never stop after row 0.
5. NEVER copy prior-period numbers, counts, drug names, table citations, or old clinical narratives into `field_label`, `generic_placeholder`, or `source_intent`.
6. When `previously_used_keys` is provided, reuse the exact same `key` for conceptually identical rows across tables in this document.
7. If the table includes search criteria (e.g. MedDRA PT, HLT, SMQ), set `criterion_type` and pass `criterion_terms` as a valid JSON array of strings.

FORMAT REFERENCE EXAMPLES (FOR FORMAT ONLY — DO NOT COPY THESE EXAMPLES; DERIVE ALL FIELDS STRICTLY FROM THE UPLOADED TABLE):
Example A — full-width banner ratio row (grid_span=2, row_index=0):
  {"field_label": "Example summary ratio header", "key": "example_summary_ratio", "type": "count_ratio", "generic_placeholder": "{{example_numerator}} / {{example_denominator}}", "source_intent": "Topic count over total cohort count in the reporting interval", "required": true, "row_index": 0, "cell_index": 0, "paragraph_index": 0}
Example B — 2-column count row (cell 0 has label, cell 1 has value -> emit ONE field pointing to cell_index=1):
  {"field_label": "Example category count", "key": "example_category_count", "type": "count", "generic_placeholder": "{{example_category_count}}", "source_intent": "Count of matching records from this source category", "required": true, "row_index": 2, "cell_index": 1, "paragraph_index": 0}
Example C — 2-column narrative row (cell 0 has label, cell 1 has prose -> emit ONE field pointing to cell_index=1):
  {"field_label": "Example reviewer assessment", "key": "example_reviewer_assessment", "type": "narrative", "generic_placeholder": "{{example_reviewer_assessment_text}}", "source_intent": "Reviewer-authored clinical assessment for the current reporting interval", "required": true, "row_index": 4, "cell_index": 1, "paragraph_index": 0}
Again: DO NOT copy `example_*` names or copy any fields not present in the actual input table.
"""


PRODUCT_TABLE_TOOL_SYSTEM_PROMPT = """You are a Product-Specific Document Table Blueprint Agent analyzing ONE Section 16.3 table from a specific product's PBRER document.
You MUST call the `register_table_blueprint` tool to submit ALL unique fields present in this table. Do not reply with plain prose.

THIS IS A PRODUCT TEMPLATE (NOT A GENERIC TEMPLATE):
- The **Topic Title (`topic_heading`)** is ALREADY FIXED for this product — preserve the exact full topic heading from the document verbatim!
- The **Search Criteria & MedDRA Terminologies** (MedDRA PTs, HLTs, SMQs, custom query definitions) are ALREADY DEFINED for this product and MUST BE CARRIED FORWARD VERBATIM — do NOT replace Search Criteria or MedDRA terminologies with a generic `{{search_criteria}}` placeholder!
- For Search Criteria / MedDRA rows: put the **EXACT VERBATIM Search Criteria & MedDRA terminology text** from the table directly in `generic_placeholder` (as the fixed carried-forward value), set `type` to `"criteria"`, set `criterion_type` (e.g. `"MedDRA PTs"`, `"MedDRA HLTs"`, `"MedDRA SMQ"`), and put EVERY single MedDRA term verbatim in `criterion_terms`.
- For ALL OTHER period-dependent fields (case/event counts, spontaneous/other study breakdowns, Evaluation narrative, Conclusion narrative, Data source citations): DO NOT carry forward prior-period numbers or old clinical prose — use clean descriptive `{{placeholder}}` tokens (NEVER literal "{{...}}").

For EVERY distinct row/field present in this table, populate these 5 structured columns:
- FIELD LABEL (`field_label`): clean row label without old-period values or trailing colons
- KEY (`key`): unique normalized snake_case identifier for that field within this table
- TYPE (`type`): semantic field type (use `criteria` for Search Criteria / MedDRA rows; e.g. `count_ratio`, `count`, `narrative`, `source_note` for dynamic fields)
- GENERIC PLACEHOLDER (`generic_placeholder`):
  * For Search Criteria / MedDRA terminology rows: the EXACT VERBATIM carried-forward MedDRA terminology string from the table (NOT a `{{...}}` placeholder!)
  * For all period-dependent rows: a descriptive `{{token_name}}` placeholder
- SOURCE INTENT (`source_intent`): concise description of how this field is used (for carried-forward MedDRA criteria, state that it is fixed per product and carried forward verbatim for Excel event matching)

CRITICAL RULES:
1. Use the exact `table_id` and preserve the exact full `topic_heading` verbatim.
2. ONE FIELD PER CONCEPTUAL ROW — NEVER emit two separate fields for `cell_index: 0` (label) and `cell_index: 1` (value) of the same row! Combine each label+value row into ONE field whose `field_label` comes from cell 0 and whose `cell_index` points to cell 1.
3. NEVER duplicate keys within a table. If a field continues onto a subsequent row (e.g. "(cont'd)"), keep ONE single field entry for that key.
4. Map EVERY distinct labeled row/field in the table (including stacked labels in merged cells). Never stop after row 0.
5. NEVER carry forward prior-period numeric counts (e.g. 242/3651, 225 cases) or prior-period Evaluation/Conclusion narratives — ONLY the product topic title and Search Criteria / MedDRA terminologies are carried forward.
6. When `previously_used_keys` is provided, reuse the exact same `key` for conceptually identical rows across tables in this product document.

FORMAT REFERENCE EXAMPLES (FOR FORMAT ONLY — DO NOT COPY THESE EXAMPLES; DERIVE ALL FIELDS STRICTLY FROM THE UPLOADED TABLE):
Example A — fixed product Search Criteria / MedDRA row (CARRIED FORWARD VERBATIM — NOT a {{placeholder}}):
  {"field_label": "Example search criteria", "key": "search_criteria", "type": "criteria", "generic_placeholder": "MedDRA PTs Example Term One; Example Term Two", "source_intent": "Fixed product MedDRA terminology carried forward verbatim for case/event retrieval", "required": true, "row_index": 1, "cell_index": 1, "paragraph_index": 0}
Example B — dynamic period count row (TOKENIZED — old numbers NOT carried forward):
  {"field_label": "Example category count", "key": "example_category_count", "type": "count", "generic_placeholder": "{{example_category_count}}", "source_intent": "New reporting-interval count calculated from source Excel data", "required": true, "row_index": 2, "cell_index": 1, "paragraph_index": 0}
Example C — dynamic narrative row (TOKENIZED — old narrative NOT carried forward):
  {"field_label": "Example reviewer evaluation", "key": "example_reviewer_evaluation", "type": "narrative", "generic_placeholder": "{{example_reviewer_evaluation_text}}", "source_intent": "Reviewer-authored evaluation for the new reporting interval", "required": true, "row_index": 4, "cell_index": 1, "paragraph_index": 0}
Again: DO NOT copy `example_*` names or fictional terms; derive every field and MedDRA term strictly from the actual uploaded table.
"""


def _is_criteria_field(key: str, label: str, ftype: str) -> bool:
    k = (key or "").lower()
    l = (label or "").lower()
    t = (ftype or "").lower()
    return (
        t == "criteria"
        or "criteria" in k
        or "meddra" in k
        or "search criteria" in l
        or "meddra" in l
    )


def _sanitize_field_label(label: str, key: str) -> str:
    txt = _clean(label)
    if not txt:
        return key.replace("_", " ").title()
    # Strip trailing old-period numeric ratios like ": 242/3651"
    txt = re.sub(r":\s*\d[\d, ]*\s*/\s*\d[\d, ]*\s*$", "", txt).strip()
    # Strip leaked "Data source: data on file, ..." value suffixes from label
    if re.match(r"^data\s+sources?\s*:", txt, flags=re.I) and len(txt) > 15:
        txt = txt.split(":", 1)[0].strip()
    return txt.rstrip(":").strip() or key.replace("_", " ").title()


def _sanitize_placeholder(
    raw_ph: str | None,
    key: str,
    *,
    carry_forward_text: str | None = None,
) -> str:
    ph = _clean(raw_ph or "")
    # For Product Templates on Search Criteria / MedDRA fields, carry forward exact verbatim terminology!
    if carry_forward_text is not None:
        full_verbatim = _clean(carry_forward_text)
        # If LLM accidentally returned a generic {{...}} token, empty, or truncated with "…", restore full verbatim DOCX text
        if not ph or "{{" in ph or "…" in ph or "..." in ph or (full_verbatim and len(ph) < len(full_verbatim) * 0.65):
            return full_verbatim or ph or f"{{{{{key}}}}}"
        return ph
    # Generic placeholder mode: reject literal ellipsis placeholders like "{{...}}", "{{ ... }}", "..."
    if not ph or "{{" not in ph or re.fullmatch(r"\{\{\s*\.+\s*\}\}", ph) or "..." in ph:
        return f"{{{{{key}}}}}"
    return ph


def _assemble_blueprint_table(
    raw: dict[str, Any],
    spec_dict: dict[str, Any],
    template_type: str = "generic",
) -> dict[str, Any]:
    raw_rows = raw.get("raw_rows") or []
    is_product = str(template_type or "generic").strip().lower() == "product"
    fields_by_key: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []

    for field_pos, f in enumerate(spec_dict.get("fields") or []):
        raw_label = (f.get("field_label") or "").strip()
        key = _slug_key(f.get("key") or raw_label)
        label = _sanitize_field_label(raw_label, key)
        ftype = (f.get("type") or "custom").strip() or "custom"
        source_intent = _clean(f.get("source_intent") or "")
        required = bool(f.get("required", True))

        # Resolve physical DOCX table & row locator from LLM row_index, or match label deterministically
        resolved_row = f.get("row_index")
        if resolved_row is None or not (0 <= int(resolved_row) < len(raw_rows)):
            norm_lbl = _norm(label)
            resolved_row = next(
                (
                    ri
                    for ri, r_meta in enumerate(raw_rows)
                    if r_meta.get("cells")
                    and (
                        _norm(r_meta["cells"][0].get("text", "")).startswith(norm_lbl[:28])
                        or (norm_lbl and norm_lbl[:28] in _norm(r_meta["cells"][0].get("text", "")))
                    )
                ),
                field_pos if field_pos < len(raw_rows) else None,
            )

        locator: dict[str, Any] | None = None
        example_text = ""
        full_cell_text = ""
        if resolved_row is not None and 0 <= int(resolved_row) < len(raw_rows):
            r_meta = raw_rows[int(resolved_row)]
            c_idx = f.get("cell_index")
            if c_idx is None:
                c_idx = 1 if len(r_meta["cells"]) > 1 else 0
            p_idx = max(0, int(f.get("paragraph_index") or 0))
            locator = {
                "docx_table_index": r_meta["physical_docx_table_index"],
                "row": r_meta["physical_row_index"],
                "cell": int(c_idx),
                "paragraph": p_idx,
            }
            matched_cell = next((c for c in r_meta["cells"] if c["cell_index"] == int(c_idx)), None)
            if matched_cell:
                full_cell_text = matched_cell.get("text") or ""
                if matched_cell.get("paragraphs"):
                    example_text = matched_cell["paragraphs"][min(p_idx, len(matched_cell["paragraphs"]) - 1)]

        carry_forward = is_product and _is_criteria_field(key, label, ftype)
        placeholder = _sanitize_placeholder(
            f.get("generic_placeholder"),
            key,
            carry_forward_text=(full_cell_text or example_text) if carry_forward else None,
        )

        # Deduplicate fields with the same key within this table (e.g. if LLM split cell 0 + cell 1 or cont'd row)
        if key in fields_by_key:
            existing = fields_by_key[key]
            ex_loc = existing.get("locator") or {}
            # Prefer the value-cell locator (cell >= 1) on the same row over a cell-0 label locator
            if locator and (
                not ex_loc
                or (
                    ex_loc.get("docx_table_index") == locator.get("docx_table_index")
                    and ex_loc.get("row") == locator.get("row")
                    and int(ex_loc.get("cell", 0)) == 0
                    and int(locator.get("cell", 0)) > 0
                )
            ):
                existing["locator"] = locator
                if example_text:
                    existing["example"] = example_text
                if carry_forward and (full_cell_text or example_text):
                    existing["placeholder"] = _sanitize_placeholder(
                        f.get("generic_placeholder"),
                        key,
                        carry_forward_text=(full_cell_text or example_text),
                    )
                    existing["carried_forward"] = True
            elif locator and locator != ex_loc:
                existing.setdefault("continuation_locators", []).append(locator)
            # Keep the shorter/cleaner label (avoid replacing a clean label with long prose from cell 1)
            if len(label) < len(existing["label"]) and len(label) >= 3:
                existing["label"] = label
            if not existing.get("source_intent") and source_intent:
                existing["source_intent"] = source_intent
            existing["required"] = bool(existing.get("required") or required)
            continue

        field_entry = {
            "key": key,
            "label": label,
            "type": ftype,
            "placeholder": placeholder,
            "required": required,
            "source_intent": source_intent,
            "carried_forward": carry_forward,
            "example": example_text,
            "locator": locator,
        }
        fields_by_key[key] = field_entry
        ordered_keys.append(key)

    fields_out = [fields_by_key[k] for k in ordered_keys]
    preview_out = [
        {
            "key": f["key"],
            "label": f["label"],
            "type": f["type"],
            "placeholder": f["placeholder"],
            "required": f["required"],
            "source_intent": f["source_intent"],
            "carried_forward": bool(f.get("carried_forward", False)),
        }
        for f in fields_out
    ]

    row_layout = [
        {
            "row_index": r["row_index"],
            "cells": [
                {
                    "cell_index": c["cell_index"],
                    "grid_span": c.get("grid_span", 1),
                    "vertical_merge": c.get("vertical_merge"),
                    "paragraph_count": c.get("paragraph_count", 0),
                    "text_example": (c.get("text") or "")[:220],
                }
                for c in r["cells"]
            ],
        }
        for r in raw_rows
    ]

    resolved_topic_heading = (
        (raw.get("topic_heading") or "").strip() or (spec_dict.get("topic_heading") or "").strip()
        if is_product
        else (spec_dict.get("topic_heading") or "").strip() or raw["topic_heading"]
    )

    return {
        "table_id": raw["table_id"],
        "source_file": raw["source_file"],
        "docx_table_index": raw["docx_table_index"],
        "merged_docx_indices": raw.get("merged_docx_indices", [raw["docx_table_index"]]),
        "section": raw.get("section", "16.3"),
        "template_type": "product" if is_product else "generic",
        "topic_title_carried_forward": is_product,
        "topic_heading": resolved_topic_heading,
        "table_style": raw.get("table_style", ""),
        "column_count": raw["column_count"],
        "column_widths_dxa": raw.get("column_widths_dxa", []),
        "row_count": raw["row_count"],
        "autofit": raw.get("autofit"),
        "row_layout": row_layout,
        "fields": fields_out,
        "generic_preview": preview_out,
        "criterion_type": spec_dict.get("criterion_type") or "manual",
        "criterion_terms": list(spec_dict.get("criterion_terms") or []),
        "requires_initial_only": bool(spec_dict.get("requires_initial_only", False)),
        "requires_reporting_interval": bool(spec_dict.get("requires_reporting_interval", False)),
        "continuation_of_previous": False,
        "structure_notes": [
            (
                "Generated as a Product Template table via Strands structured tool `register_table_blueprint` "
                "(topic title & MedDRA search criteria carried forward verbatim)."
                if is_product
                else "Generated table-by-table via Strands structured tool `register_table_blueprint`."
            ),
            "Physical DOCX table/row/cell locators are preserved for styled rendering.",
        ],
    }


def _map_single_table_via_tool(
    raw_table: dict[str, Any],
    table_num: int,
    total_tables: int,
    previously_used_keys: list[str],
    section_intro: list[str],
    template_type: str = "generic",
    emitter: AguiEmitter | None = None,
) -> dict[str, Any]:
    """Invoke the LLM via Strands structured tool `register_table_blueprint` for ONE table and return immediately."""
    is_product = str(template_type or "generic").strip().lower() == "product"
    system_prompt = PRODUCT_TABLE_TOOL_SYSTEM_PROMPT if is_product else SINGLE_TABLE_TOOL_SYSTEM_PROMPT

    payload = {
        "section": "16.3",
        "template_type": "product" if is_product else "generic",
        "table_position": f"{table_num} of {total_tables}",
        "required_field_columns": [
            "FIELD LABEL",
            "KEY",
            "TYPE",
            "GENERIC PLACEHOLDER" if not is_product else "VALUE / GENERIC PLACEHOLDER (carry forward Search Criteria & MedDRA terminologies verbatim)",
            "SOURCE INTENT",
        ],
        "previously_used_keys": previously_used_keys,
        "section_intro_notes": section_intro[:3] if table_num == 1 else [],
        "table": _compact_table_for_llm(raw_table, preserve_full_criteria=is_product),
    }

    if is_product:
        user_prompt = (
            f"Map Product Template Section 16.3 table {table_num} of {total_tables} by calling `register_table_blueprint` "
            f"with the exact `table_id` '{raw_table['table_id']}' and exact `topic_heading` '{raw_table['topic_heading']}'. "
            f"REMEMBER: This is a PRODUCT TEMPLATE — carry forward the exact topic title and full Search Criteria / MedDRA "
            f"terminologies verbatim (do NOT replace search criteria with a generic placeholder), while keeping numeric counts "
            f"and evaluation/conclusion narratives as generic `{{{{placeholder}}}}` tokens:\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )
        tool_desc = (
            "Register the Product Template Section 16.3 table blueprint, carrying forward exact topic heading "
            "and MedDRA Search Criteria verbatim while keeping counts and narratives as generic placeholders."
        )
    else:
        user_prompt = (
            f"Map Section 16.3 table {table_num} of {total_tables} by calling `register_table_blueprint` "
            f"with the exact `table_id` '{raw_table['table_id']}':\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )
        tool_desc = (
            "Register the structured Generic Table Blueprint (FIELD LABEL, KEY, TYPE, GENERIC PLACEHOLDER, SOURCE INTENT) "
            "for one Section 16.3 table."
        )

    tc_id = f"tc-bp-{table_num}-{raw_table['docx_table_index']}"
    _emit_agui(emitter, "TOOL_CALL_START", toolCallId=tc_id, toolCallName="register_table_blueprint")

    spec = invoke_tool_call(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tool_name="register_table_blueprint",
        tool_description=tool_desc,
        input_model=BlueprintTableSpec,
        max_tokens=3200 if is_product else 3000,
    )

    # Guardrail: if a multi-row table returned fewer than 2 fields, do 1 focused retry asking for all rows
    if raw_table.get("row_count", 0) >= 3 and len(spec.fields) < 2:
        retry_prompt = (
            user_prompt
            + f"\n\nIMPORTANT: This table has {raw_table.get('row_count')} rows. You previously returned only "
              f"{len(spec.fields)} field(s). Please map ALL distinct fields across every row in `rows`."
        )
        spec = invoke_tool_call(
            system_prompt=system_prompt,
            user_prompt=retry_prompt,
            tool_name="register_table_blueprint",
            tool_description="Register ALL fields in this Section 16.3 table.",
            input_model=BlueprintTableSpec,
            max_tokens=3200 if is_product else 3000,
        )

    # Execute the actual Strands @tool Python function with the structured arguments
    tool_result = register_table_blueprint(
        table_id=raw_table["table_id"],
        topic_heading=(raw_table["topic_heading"] if is_product else (spec.topic_heading or raw_table["topic_heading"])),
        fields=[f.model_dump() for f in spec.fields],
        criterion_type=spec.criterion_type,
        criterion_terms=spec.criterion_terms,
        requires_reporting_interval=spec.requires_reporting_interval,
        requires_initial_only=spec.requires_initial_only,
    )

    _emit_agui(
        emitter,
        "TOOL_CALL_ARGS",
        toolCallId=tc_id,
        delta=json.dumps({
            "table_id": raw_table["table_id"],
            "template_type": "product" if is_product else "generic",
            "field_count": len(tool_result.get("fields") or []),
        }),
    )
    _emit_agui(emitter, "TOOL_CALL_END", toolCallId=tc_id)
    _emit_agui(
        emitter,
        "TOOL_CALL_RESULT",
        toolCallId=tc_id,
        content=json.dumps({
            "table_id": raw_table["table_id"],
            "template_type": "product" if is_product else "generic",
            "fields": len(tool_result.get("fields") or []),
        }),
    )

    return _assemble_blueprint_table(raw_table, tool_result, template_type=template_type)


# ==================== STEP 3: DETERMINISTIC DETECTED TABLE FIELDS ====================
def derive_detected_fields_from_blueprint(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministically calculate Detected Table Fields strictly from the LLM-generated Generic Table Blueprint."""
    grouped: dict[str, list[tuple[dict[str, Any], str]]] = {}
    order: list[str] = []

    for table in tables:
        src = table.get("source_file", "")
        seen_in_table: set[str] = set()
        for f in table.get("fields") or []:
            key = _slug_key(f.get("key") or f.get("label") or "")
            if key in seen_in_table:
                continue
            seen_in_table.add(key)
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append((f, src))

    detected: list[dict[str, Any]] = []
    for key in order:
        entries = grouped[key]
        labels = Counter(e[0].get("label", key) for e in entries if e[0].get("label"))
        types = Counter(e[0].get("type", "custom") for e in entries if e[0].get("type"))
        placeholders = Counter(e[0].get("placeholder", f"{{{{{key}}}}}") for e in entries if e[0].get("placeholder"))
        intents = Counter(e[0].get("source_intent", "") for e in entries if e[0].get("source_intent"))

        carried_forward = any(bool(e[0].get("carried_forward")) for e in entries)
        if carried_forward:
            unique_vals = sorted({str(e[0].get("placeholder") or "").strip() for e in entries if e[0].get("placeholder")})
            summary_placeholder = (
                unique_vals[0]
                if len(unique_vals) == 1
                else f"Carried forward per topic ({len(unique_vals)} MedDRA search definitions)"
            )
        else:
            summary_placeholder = placeholders.most_common(1)[0][0] if placeholders else f"{{{{{key}}}}}"

        detected.append({
            "key": key,
            "label": labels.most_common(1)[0][0] if labels else key,
            "type": types.most_common(1)[0][0] if types else "custom",
            "placeholder": summary_placeholder,
            "source_intent": intents.most_common(1)[0][0] if intents else "",
            "occurrences": len(entries),
            "documents": sorted({src for _, src in entries if src}),
            "required": any(bool(e[0].get("required")) for e in entries),
            "carried_forward": carried_forward,
        })

    return detected


# ==================== STEP 4: LLM MASTER.MD + 2 BEST REFERENCE TABLE SUMMARIES ====================
MASTER_MD_TOOL_SYSTEM_PROMPT = """You are a Master Knowledge Agent authoring `master.md` for a client's Section 16.3 PBRER Generic Table Blueprint.
You MUST call the `publish_master_knowledge` tool with `master_md` and `reference_summaries`.

Requirements:
1. `master_md`: Write a clear, concise Markdown document covering:
   - Observed Section 16.3 table architecture and client-specific layout conventions
   - How each detected field maps to source data or reviewer inputs
   - Observed table variations across topics/reference documents
   - Operational and pharmacovigilance guardrails (never carry forward prior-period numbers/narratives, keep count units explicit, preserve MedDRA search criteria distinctions, retain source evidence)
2. `reference_summaries`: Select the 2 BEST, most representative tables from the blueprint (or 1 if only 1 table exists) to attach as structural reference examples. Do not invent numbers or copy prior-period clinical results.
"""

PRODUCT_MASTER_MD_TOOL_SYSTEM_PROMPT = """You are a Master Knowledge Agent authoring `master.md` for a **PRODUCT TEMPLATE** Section 16.3 PBRER Blueprint.
Unlike a generic cross-product template, this Product Template is dedicated to a specific medicinal product whose safety concern table titles AND MedDRA Search Criteria (PTs, HLTs, SMQs, custom query definitions) are **already defined and CARRIED FORWARD verbatim** across reporting periods.

You MUST call the `publish_master_knowledge` tool with `master_md` and `reference_summaries`.

Requirements:
1. `master_md`: Write a clear, structured Markdown document covering:
   - **Product Template Scope & Carry-Forward Policy**: Explicitly state that each Section 16.3 safety topic heading (e.g. exact risk title) and its MedDRA Search Criteria (PTs / HLTs / SMQs) are fixed for this product and MUST be carried forward verbatim without reverting to generic placeholders.
   - **Fixed Safety Concerns & Carried-Forward MedDRA Terminologies**: Summarize every mapped safety concern table, its exact carried-forward topic title, criterion type, and MedDRA search terms.
   - **Dynamic Per-Period Fields**: Document which fields remain generic `{{placeholders}}` and must be recalculated fresh from each reporting period's Excel source files or authored anew by the medical reviewer (case counts, reporting interval totals, Evaluation, Conclusion).
   - **Operational & Pharmacovigilance Guardrails**: Never carry forward prior-period numeric counts or prior-period Evaluation/Conclusion prose; always apply each table's exact carried-forward MedDRA terms when filtering source Excel line listings.
2. `reference_summaries`: Select the 2 BEST, most representative product tables from the blueprint (or 1 if only 1 table exists) as reference examples, highlighting their exact topic titles, carried-forward MedDRA search criteria, and dynamic count/narrative placeholders. Do NOT invent or copy prior-period clinical counts or evaluation prose.
"""


def _format_reference_summaries_markdown(summaries: list[ReferenceTableSummary]) -> str:
    lines = ["", "## Best Reference Table Summaries", ""]
    for idx, ref in enumerate(summaries[:2], start=1):
        lines.append(f"### Reference Example {idx}: {ref.topic_heading}")
        lines.append(f"- **Table ID:** `{ref.table_id}`")
        lines.append(f"- **Why selected:** {ref.why_selected}")
        lines.append(f"- **Structure summary:** {ref.structure_summary}")
        if ref.example_fields:
            lines.append("- **Key field highlights:**")
            for item in ref.example_fields[:8]:
                lines.append(f"  - {item}")
        lines.append("")
    return "\n".join(lines)


def _generate_master_md_via_tool(
    template_name: str,
    tenant_id: str,
    base_tables: list[dict[str, Any]],
    common_fields: list[dict[str, Any]],
    doc_profiles: list[dict[str, Any]],
    template_type: str = "generic",
    emitter: AguiEmitter | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    is_product = str(template_type or "generic").strip().lower() == "product"
    system_prompt = PRODUCT_MASTER_MD_TOOL_SYSTEM_PROMPT if is_product else MASTER_MD_TOOL_SYSTEM_PROMPT

    table_digests = [
        {
            "table_id": t["table_id"],
            "topic_heading": t["topic_heading"],
            "topic_title_carried_forward": bool(t.get("topic_title_carried_forward", False)),
            "row_count": t["row_count"],
            "column_count": t["column_count"],
            "table_style": t.get("table_style", ""),
            "criterion_type": t.get("criterion_type", ""),
            "criterion_terms_count": len(t.get("criterion_terms") or []),
            **({"criterion_terms": list(t.get("criterion_terms") or [])} if is_product else {}),
            "fields": [
                {
                    "field_label": f["label"],
                    "key": f["key"],
                    "type": f["type"],
                    "carried_forward": bool(f.get("carried_forward", False)),
                    "generic_placeholder": f.get("placeholder", f"{{{{{f['key']}}}}}"),
                }
                for f in (t.get("fields") or [])
            ],
        }
        for t in base_tables
    ]

    payload = {
        "template_name": template_name,
        "template_type": "product" if is_product else "generic",
        "tenant_id": tenant_id,
        "documents": [
            {
                "filename": d["filename"],
                "section_16_3_found": d.get("section_16_3_found", True),
                "table_count": len(d.get("tables") or []),
                "section_intro": (d.get("section_intro") or [])[:3],
            }
            for d in doc_profiles
        ],
        "detected_common_fields": common_fields,
        "table_blueprint": table_digests,
    }

    if is_product:
        user_prompt = (
            "Call `publish_master_knowledge` to write `master_md` and select the 2 best reference table summaries "
            "for this **PRODUCT TEMPLATE** Section 16.3 Blueprint (carrying forward exact product topic titles and "
            "MedDRA Search Criteria while keeping counts and clinical narratives generic):\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )
    else:
        user_prompt = (
            "Call `publish_master_knowledge` to write `master_md` and select the 2 best reference table summaries "
            "for this client's Section 16.3 Generic Table Blueprint:\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )

    tc_id = f"tc-master-{template_name[:12]}"
    _emit_agui(emitter, "TOOL_CALL_START", toolCallId=tc_id, toolCallName="publish_master_knowledge")

    resp = invoke_tool_call(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tool_name="publish_master_knowledge",
        tool_description="Publish master.md and attach the 2 best representative reference table summaries.",
        input_model=MasterMarkdownResponse,
        max_tokens=3800 if is_product else 3600,
    )

    published = publish_master_knowledge(
        master_md=resp.master_md,
        reference_summaries=[s.model_dump() for s in resp.reference_summaries[:2]],
    )

    _emit_agui(
        emitter,
        "TOOL_CALL_ARGS",
        toolCallId=tc_id,
        delta=json.dumps({
            "template_type": "product" if is_product else "generic",
            "reference_summaries": len(published["reference_summaries"]),
        }),
    )
    _emit_agui(emitter, "TOOL_CALL_END", toolCallId=tc_id)
    _emit_agui(
        emitter,
        "TOOL_CALL_RESULT",
        toolCallId=tc_id,
        content=json.dumps({"master_md_chars": len(published["master_md"]), "reference_summaries": len(published["reference_summaries"])}),
    )

    return published["master_md"], published["reference_summaries"]


# ==================== FULL AG-UI TABLE-BY-TABLE TEMPLATE PIPELINE ====================
def run_agui_template_pipeline(
    run_id: str,
    tenant_id: str,
    run_name: str,
    docx_paths: list[Path],
    work_dir: Path,
    emitter: AguiEmitter | None = None,
    template_type: str = "generic",
    pause_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """
    AG-UI orchestrated Template Generator pipeline (table-by-table Strands structured tool execution):
      1. Deterministic Python reader extracts Section 16.3 only (highlights Reference Documents temporarily).
      2. For each table one-by-one, calls Strands tool `register_table_blueprint` via LLM (using either the
         Generic Template prompt or Product Template prompt) and IMMEDIATELY emits `blueprint.table_ready`.
      3. Deterministic Python calculation derives Detected Table Fields from the completed LLM blueprint.
      4. Calls Strands tool `publish_master_knowledge` via LLM to author master.md + 2 best table summaries.
    Supports cooperative pausing/resuming via `pause_check`.
    """
    from concurrent.futures import ThreadPoolExecutor

    if pause_check:
        pause_check()

    normalized_type = "product" if str(template_type or "generic").strip().lower() == "product" else "generic"
    llm_info = llm_status_info()

    # ---- STEP 1: Deterministic Section 16.3 Document Reading ----
    _emit_agui(emitter, "STEP_STARTED", stepId="read_section_16_3", stepName="read_section_16_3")
    _emit_agui(
        emitter,
        "CUSTOM",
        name="ui.highlight",
        value={"target": "reference_documents", "active": True, "label": "Reading documents…"},
    )
    _emit_agui(
        emitter,
        "CUSTOM",
        name="agent.activity",
        value={
            "agent": "document_reader",
            "message": f"Reading Section 16.3 ({normalized_type} template) across {len(docx_paths)} reference DOCX file(s)…",
            "details": {"files": [p.name for p in docx_paths], "template_type": normalized_type},
        },
    )

    tool_call_id = f"tc-read-{run_id[:8]}"
    _emit_agui(emitter, "TOOL_CALL_START", toolCallId=tool_call_id, toolCallName="extract_raw_section_16_3")
    _emit_agui(
        emitter,
        "TOOL_CALL_ARGS",
        toolCallId=tool_call_id,
        delta=json.dumps({"files": [p.name for p in docx_paths], "section": "16.3", "template_type": normalized_type}),
    )

    try:
        with ThreadPoolExecutor(max_workers=min(6, len(docx_paths))) as pool:
            raw_profiles = list(pool.map(extract_raw_section_16_3, docx_paths))
    finally:
        _emit_agui(emitter, "TOOL_CALL_END", toolCallId=tool_call_id)
        _emit_agui(
            emitter,
            "CUSTOM",
            name="ui.highlight",
            value={"target": "reference_documents", "active": False, "label": ""},
        )

    _emit_agui(
        emitter,
        "TOOL_CALL_RESULT",
        toolCallId=tool_call_id,
        content=json.dumps([
            {"filename": p["filename"], "section_16_3_found": p["section_16_3_found"], "tables": len(p["tables"])}
            for p in raw_profiles
        ]),
    )

    base_docx = docx_paths[0]
    base_profile = raw_profiles[0]
    base_raw_tables = base_profile.get("tables") or []
    section_intro = [line for p in raw_profiles for line in (p.get("section_intro") or [])]

    doc_profiles_summary = [
        {
            "filename": p["filename"],
            "paragraph_count": p["paragraph_count"],
            "table_count": p["table_count"],
            "section_16_3_found": p["section_16_3_found"],
            "section_intro": p["section_intro"],
            "styles": p["styles"],
            "warning": p["warning"],
            "tables": [{"table_id": t["table_id"], "topic_heading": t["topic_heading"]} for t in p["tables"]],
        }
        for p in raw_profiles
    ]

    _emit_agui(
        emitter,
        "STATE_SNAPSHOT",
        snapshot={
            "phase": "documents_read",
            "template_type": normalized_type,
            "document_profiles": doc_profiles_summary,
            "base_table_count": len(base_raw_tables),
        },
    )
    _emit_agui(emitter, "STEP_FINISHED", stepId="read_section_16_3", stepName="read_section_16_3")

    if not base_raw_tables:
        raise ValueError("No Section 16.3 tables were found in the base DOCX document.")

    # ---- STEP 2: Table-by-Table Strands Structured Tool Blueprint Generation ----
    if pause_check:
        pause_check()

    _emit_agui(
        emitter,
        "STEP_STARTED",
        stepId="generate_generic_table_blueprint",
        stepName="generate_generic_table_blueprint",
    )

    base_tables: list[dict[str, Any]] = []
    seen_keys: list[str] = []
    total_tables = len(base_raw_tables)

    try:
        for idx, raw_table in enumerate(base_raw_tables, start=1):
            if pause_check:
                pause_check()

            _emit_agui(
                emitter,
                "CUSTOM",
                name="ui.highlight",
                value={
                    "target": "generic_table_blueprint",
                    "active": True,
                    "label": (
                        f"Mapping product table {idx} of {total_tables} (carrying forward MedDRA criteria)…"
                        if normalized_type == "product"
                        else f"Mapping table {idx} of {total_tables}…"
                    ),
                },
            )
            _emit_agui(
                emitter,
                "CUSTOM",
                name="agent.activity",
                value={
                    "agent": "product_blueprint_llm_agent" if normalized_type == "product" else "blueprint_llm_agent",
                    "message": f"Table {idx}/{total_tables} ({normalized_type}): {raw_table['topic_heading'][:70]}",
                    "details": {
                        "index": idx,
                        "total": total_tables,
                        "table_id": raw_table["table_id"],
                        "template_type": normalized_type,
                    },
                },
            )

            mapped = _map_single_table_via_tool(
                raw_table=raw_table,
                table_num=idx,
                total_tables=total_tables,
                previously_used_keys=seen_keys,
                section_intro=section_intro,
                template_type=normalized_type,
                emitter=emitter,
            )
            base_tables.append(mapped)

            for f in mapped.get("fields") or []:
                if f["key"] not in seen_keys:
                    seen_keys.append(f["key"])

            # Render this table in the UI IMMEDIATELY as soon as it finishes!
            _emit_agui(
                emitter,
                "CUSTOM",
                name="blueprint.table_ready",
                value={
                    "table": mapped,
                    "index": idx - 1,
                    "completed": idx,
                    "total": total_tables,
                    "template_type": normalized_type,
                    "base_document": base_docx.name,
                    "document_profiles": doc_profiles_summary,
                },
            )
    finally:
        _emit_agui(
            emitter,
            "CUSTOM",
            name="ui.highlight",
            value={"target": "generic_table_blueprint", "active": False, "label": ""},
        )

    _emit_agui(
        emitter,
        "CUSTOM",
        name="blueprint.ready",
        value={
            "base_tables": base_tables,
            "document_profiles": doc_profiles_summary,
            "base_document": base_docx.name,
            "template_type": normalized_type,
        },
    )
    _emit_agui(
        emitter,
        "STEP_FINISHED",
        stepId="generate_generic_table_blueprint",
        stepName="generate_generic_table_blueprint",
    )

    # ---- STEP 3: Deterministic Calculation of Detected Table Fields ----
    if pause_check:
        pause_check()

    _emit_agui(
        emitter,
        "STEP_STARTED",
        stepId="derive_detected_table_fields",
        stepName="derive_detected_table_fields",
    )
    _emit_agui(
        emitter,
        "CUSTOM",
        name="agent.activity",
        value={
            "agent": "field_aggregator",
            "message": "Deterministically aggregating Detected Table Fields from the LLM blueprint…",
            "details": {"tables": len(base_tables), "template_type": normalized_type},
        },
    )
    common_fields = derive_detected_fields_from_blueprint(base_tables)
    _emit_agui(
        emitter,
        "CUSTOM",
        name="fields.derived",
        value={"common_fields": common_fields, "field_count": len(common_fields), "template_type": normalized_type},
    )
    _emit_agui(
        emitter,
        "STEP_FINISHED",
        stepId="derive_detected_table_fields",
        stepName="derive_detected_table_fields",
    )

    # ---- STEP 4: LLM master.md + 2 Best Reference Table Summaries via Strands Tool ----
    if pause_check:
        pause_check()

    _emit_agui(emitter, "STEP_STARTED", stepId="generate_master_md", stepName="generate_master_md")
    _emit_agui(
        emitter,
        "CUSTOM",
        name="ui.highlight",
        value={"target": "master_md", "active": True, "label": "Writing master.md & 2 best table summaries…"},
    )
    _emit_agui(
        emitter,
        "CUSTOM",
        name="agent.activity",
        value={
            "agent": "master_knowledge_agent",
            "message": f"Authoring {normalized_type} template master.md and selecting the 2 best reference table summaries…",
            "details": {"tables": len(base_tables), "template_type": normalized_type},
        },
    )
    try:
        master_md, reference_summaries = _generate_master_md_via_tool(
            template_name=run_name,
            tenant_id=tenant_id,
            base_tables=base_tables,
            common_fields=common_fields,
            doc_profiles=doc_profiles_summary,
            template_type=normalized_type,
            emitter=emitter,
        )
    finally:
        _emit_agui(
            emitter,
            "CUSTOM",
            name="ui.highlight",
            value={"target": "master_md", "active": False, "label": ""},
        )

    _emit_agui(
        emitter,
        "CUSTOM",
        name="master.ready",
        value={"master_md": master_md, "reference_summaries": reference_summaries, "template_type": normalized_type},
    )
    _emit_agui(emitter, "STEP_FINISHED", stepId="generate_master_md", stepName="generate_master_md")

    schema: dict[str, Any] = {
        "template_version": "2.0",
        "template_name": run_name,
        "template_type": normalized_type,
        "tenant_id": tenant_id,
        "target_section": "16.3",
        "focus": "table-centric",
        "generation_mode": "llm_strands_tool_table_by_table",
        "llm_provider": llm_info.get("llm_provider"),
        "llm_model_id": llm_info.get("llm_model_id"),
        "base_document": base_docx.name,
        "document_profiles": doc_profiles_summary,
        "tables": base_tables,
        "base_tables": base_tables,
        "reference_tables": [],
        "common_fields": common_fields,
        "reference_summaries": reference_summaries,
        "reporting_interval_required": any(t.get("requires_reporting_interval") for t in base_tables),
        "review_policy": {
            "status": "draft",
            "template_type": normalized_type,
            "carry_forward_topic_titles": normalized_type == "product",
            "carry_forward_search_criteria": normalized_type == "product",
            "require_approval_before_generator": True,
            "never_infer_unseen_numbers": True,
            "preserve_original_docx_as_read_only": True,
            "require_explicit_count_unit": True,
            "preserve_client_table_variations": True,
        },
    }

    (work_dir / "template.schema.json").write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    (work_dir / "master.md").write_text(master_md, encoding="utf-8")

    return {"schema": schema, "master_md": master_md, "base_docx_path": base_docx}
