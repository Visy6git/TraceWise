"""Stage 1 Phase 1B: Subsection-by-subsection Claim Extraction using Strands Agent & @tool."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.config import MOCK_RUNS_ENABLED, is_live_llm_enabled
from app.services.event_stream import default_broker
from app.stages.stage_1_claims.claim_tools import ClaimToolsetContext, create_claim_extraction_tools
from app.stages.stage_1_claims.section_scope import render_subsection_full_context
from app.stages.strands_factory import AgentRuntimeConfig, build_strands_agent

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    p = Path(__file__).resolve().parents[2] / "prompts" / "claim_extractor.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _pick_best_source_for_subsection(
    unit: dict[str, Any],
    file_profiles: list[dict[str, Any]],
) -> list[str]:
    """Keyword match subsection title against uploaded source filenames with clean fallback."""
    title_tokens = set(unit.get("keywords") or [])
    if not title_tokens:
        title_tokens = {
            t for t in re.sub(r"[^a-z0-9]+", " ", unit.get("title", "").lower()).split() if len(t) >= 4
        }

    scored: list[tuple[int, str]] = []
    all_case: list[str] = []
    for prof in file_profiles:
        fn = prof["filename"]
        norm = re.sub(r"[^a-z0-9]+", " ", fn.lower())
        if "all" in norm.split():
            all_case.append(fn)
        score = sum(1 for tok in title_tokens if tok in norm)
        if score > 0:
            scored.append((score, fn))

    scored.sort(key=lambda x: x[0], reverse=True)
    if scored:
        chosen = [fn for _, fn in scored[:2]]
        return chosen
    if all_case:
        return all_case[:1]
    return [p["filename"] for p in file_profiles[:1]]


def _extract_deterministic_claims_via_tool(
    unit: dict[str, Any],
    register_fn: Any,
    file_profiles: list[dict[str, Any]],
) -> None:
    """Deterministic subsection extractor invoking the exact same Strands @tool validation."""
    blocks = unit.get("blocks") or []
    full_text = "\n".join(b.get("text", "") for b in blocks if b.get("type") != "table")
    first_block_id = next((b.get("block_id", "") for b in blocks if b.get("block_id")), "")

    # Extract search criteria from table row or prose
    search_criteria = ""
    ratio_candidates: list[tuple[str, str, str, str]] = []  # (num, denom, label, blk_id)
    table_children: list[dict[str, Any]] = []

    for b in blocks:
        blk_id = b.get("block_id", "")
        if b.get("type") == "table":
            headers = [str(h) for h in (b.get("headers") or [])]
            for row in b.get("rows") or []:
                row_text = " ".join(str(c) for c in row)
                if "search criteria" in row_text.lower():
                    val = str(row[-1] if len(row) > 1 else row_text).strip()
                    if val:
                        search_criteria = val
                # Check for X / Y pattern inside cells
                m_ratio = re.search(r"\b(\d{1,5})\s*/\s*(\d{1,6})\b", row_text)
                if m_ratio and len(row) >= 2:
                    ratio_candidates.append(
                        (m_ratio.group(1), m_ratio.group(2), f"{row[0]} ({m_ratio.group(0)})", blk_id)
                    )
                # Look for serious/fatal or source breakdowns inside table cells
                for cell in row[1:]:
                    c_str = str(cell)
                    for m in re.finditer(r"(Spontaneous|Report from other studies|Literature):\s*(\d+)", c_str, re.I):
                        table_children.append(
                            {
                                "raw_statement": f"{m.group(1)}: {m.group(2)} case(s)",
                                "normalized_statement": f"{m.group(1)} source count is {m.group(2)} cases",
                                "claim_type": "source_split",
                                "entity_unit": "Distinct case",
                                "reported_value": m.group(2),
                                "unit": "cases",
                                "relationship": "source_split",
                                "block_id": blk_id,
                            }
                        )
                    m_ser = re.search(r"\b(\d+)\s*\(([\d.]+%)\)\s*cases?\s+were\s+serious", c_str, re.I)
                    if m_ser:
                        table_children.append(
                            {
                                "raw_statement": f"{m_ser.group(1)} ({m_ser.group(2)}) cases were serious",
                                "normalized_statement": f"Serious case subset equals {m_ser.group(1)} cases",
                                "claim_type": "distinct_case_count",
                                "entity_unit": "Distinct serious case",
                                "reported_value": m_ser.group(1),
                                "numerator": m_ser.group(1),
                                "unit": "cases",
                                "relationship": "serious_subset",
                                "block_id": blk_id,
                            }
                        )
                    m_fat = re.search(r"\b(\d+)\s*\(([\d.]+%)\)\s*case\s+(?:was\s+)?fatal", c_str, re.I)
                    if m_fat:
                        table_children.append(
                            {
                                "raw_statement": m_fat.group(0),
                                "normalized_statement": f"Fatal case subset equals {m_fat.group(1)} cases",
                                "claim_type": "distinct_case_count",
                                "entity_unit": "Fatal case",
                                "reported_value": m_fat.group(1),
                                "numerator": m_fat.group(1),
                                "unit": "cases",
                                "relationship": "fatal_subset",
                                "block_id": blk_id,
                            }
                        )

        else:
            txt = b.get("text") or ""
            m_ratio = re.search(r"\b(\d{1,5})\s*/\s*(\d{1,6})\s*(?:cases?|events?)", txt, re.I)
            if m_ratio:
                ratio_candidates.append(
                    (m_ratio.group(1), m_ratio.group(2), txt.strip(), blk_id)
                )

    if not search_criteria:
        m_crit = re.search(
            r"(?:MedDRA\s+(?:PTs?|HLTs?|SMQ)[^.\n]+|Search\s+criteria[^.\n]+)",
            full_text,
            re.I,
        )
        search_criteria = m_crit.group(0).strip() if m_crit else f"Section {unit['section_number']} ({unit['title']})"

    mapped = _pick_best_source_for_subsection(unit, file_profiles)
    if not mapped:
        return

    primary_file = mapped[0]
    prof = next((p for p in file_profiles if p["filename"] == primary_file), None)
    data_sheet = next((s for s in (prof or {}).get("sheets", []) if s.get("is_data")), None)
    sheet_name = data_sheet["sheet_name"] if data_sheet else "Sheet1"
    header_idx = data_sheet["header_row_index"] if data_sheet else 0
    cols = [c["name"] for c in (data_sheet["columns"] if data_sheet else [])[:8]]
    dedup_key = next(
        (c for c in cols if "case" in c.lower() and ("number" in c.lower() or "id" in c.lower())),
        cols[0] if cols else "Case Number",
    )

    if ratio_candidates:
        num, denom, raw_stmt, blk_id = ratio_candidates[0]
        # De-duplicate children
        seen_ch: set[str] = set()
        unique_children: list[dict[str, Any]] = []
        for ch in table_children:
            key = f"{ch['relationship']}:{ch['reported_value']}"
            if key not in seen_ch:
                seen_ch.add(key)
                unique_children.append(ch)

        register_fn(
            section_number=unit["section_number"],
            parent_statement=raw_stmt,
            parent_normalized_statement=(
                f"{unit['title']}: {num} interval cases out of {denom} cumulative cases"
            ),
            parent_claim_type="distinct_case_count",
            parent_entity_unit="Distinct case",
            parent_reported_value=num,
            parent_unit="cases",
            parent_numerator=num,
            parent_denominator=denom,
            parent_block_id=blk_id or first_block_id,
            search_criteria=search_criteria,
            source_document_mapped=mapped,
            children_claims=unique_children,
            hint_text=(
                f"Filter `{primary_file}` sheet `{sheet_name}` (`header_row_index={header_idx}`) "
                f"for interval cases matching criteria `{search_criteria}`, deduplicating on `{dedup_key}`."
            ),
            hint_observed=[
                f"Subsection {unit['section_number']} states {num}/{denom} cases",
                f"Source sheet `{sheet_name}` header starts at 0-based row {header_idx}",
            ],
            hint_inferred=[
                f"Distinct `{dedup_key}` count in reporting interval reproduces parent claim and child splits"
            ],
            hint_unknowns=[],
            verification_plan={
                "source_file": primary_file,
                "sheet": sheet_name,
                "header_row_index": header_idx,
                "columns": cols,
                "filters": [search_criteria],
                "dedup_key": dedup_key,
                "aggregation": "nunique",
                "expected_value": num,
            },
        )
        return

    # Fallback: check for explicit single numeric case/event/literature count in prose
    m_single = re.search(
        r"\b(\d+|one|two|three|four|five)\s+(?:relevant\s+)?(?:cases?|events?|patients?|literature\s+articles?)\b",
        full_text,
        re.I,
    )
    if m_single:
        word_map = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5"}
        raw_token = m_single.group(1).lower()
        val_str = word_map.get(raw_token, raw_token)
        register_fn(
            section_number=unit["section_number"],
            parent_statement=m_single.group(0),
            parent_normalized_statement=f"{unit['title']}: {val_str} reported items",
            parent_claim_type="distinct_case_count",
            parent_entity_unit="Distinct case",
            parent_reported_value=val_str,
            parent_unit="cases",
            parent_block_id=first_block_id,
            search_criteria=search_criteria,
            source_document_mapped=mapped,
            children_claims=[],
            hint_text=f"Verify count `{val_str}` in `{primary_file}` using search criteria `{search_criteria}`.",
            hint_observed=[f"Subsection text reports {m_single.group(0)}"],
            hint_inferred=[],
            hint_unknowns=[],
            verification_plan={
                "source_file": primary_file,
                "sheet": sheet_name,
                "header_row_index": header_idx,
                "columns": cols,
                "dedup_key": dedup_key,
                "aggregation": "nunique",
                "expected_value": val_str,
            },
        )


def extract_claims_by_subsection(
    *,
    run_id: str,
    doc_data: dict[str, Any],
    master_summary_md: str,
    per_file_mds: dict[str, str],
    file_profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Navigate Section 16.3 subsection-by-subsection using Strands Agent + Master Summary .md."""
    scope = doc_data["scope"]
    work_units: list[dict[str, Any]] = scope["work_units"]
    sections_by_number = {s["number"]: s for s in doc_data["sections"]}
    uploaded_filenames = [p["filename"] for p in file_profiles]

    ctx = ClaimToolsetContext(
        run_id=run_id,
        target_filename=doc_data["filename"],
        sections_by_number=sections_by_number,
        uploaded_filenames=uploaded_filenames,
        per_file_mds=per_file_mds,
    )
    tools = create_claim_extraction_tools(ctx)
    register_tool = tools[0]
    system_prompt = _load_prompt()

    use_live = is_live_llm_enabled() and not MOCK_RUNS_ENABLED
    agent = None
    if use_live:
        agent = build_strands_agent(
            AgentRuntimeConfig(
                agent_id="ClaimExtractorStrands",
                stage="claims",
                model_id=None,
                system_prompt=system_prompt,
                max_turns=12,
                run_id=run_id,
            ),
            tools=tools,
        )

    for idx, unit in enumerate(work_units, start=1):
        sec_num = unit["section_number"]
        sec_title = unit["title"]
        default_broker.emit_activity(
            run_id=run_id,
            stage="claims",
            title=f"Extracting claims ({idx}/{len(work_units)}): {sec_num} {sec_title}",
            detail="Strands agent processing full subsection context + Master Summary .md",
            kind="agent",
            agent="ClaimExtractorStrands",
        )

        subsection_context = render_subsection_full_context(unit)

        if agent is not None:
            user_prompt = (
                f"# Master Summary of Source Documents\n\n{master_summary_md}\n\n"
                f"---\n\n"
                f"# Target Document Subsection ({idx}/{len(work_units)})\n\n"
                f"{subsection_context}\n\n"
                f"---\n"
                f"Identify every quantitative claim in Subsection `{sec_num}` above and call "
                f"`register_claim_group` for each parent claim (+ optional `children_claims`, "
                f"`search_criteria`, `source_document_mapped`, and grounded `hint_text`)."
            )
            try:
                agent(user_prompt)
            except Exception as exc:
                logger.exception(
                    "Strands extraction failed on subsection %s for run %s: %s",
                    sec_num,
                    run_id,
                    exc,
                )
                raise
        else:
            _extract_deterministic_claims_via_tool(unit, register_tool, file_profiles)

    return ctx.registered_claims

