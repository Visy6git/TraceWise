"""Stage 1: Claims Orchestrator — focused on PBRER Section 16.3.

The orchestrator reads only Section 16.3 ("Evaluation of Risks and New
Information"), decomposes it into its leaf subsections (each a risk topic such
as Cardiac failure, Impulse control disorders, Hallucinations, DAWS,
Augmentation, Suicide-related behaviour, ...), and dispatches ONE
claim-extraction subagent per subsection. Each subagent gets a small, bounded
prompt (only that subsection's blocks + its matching source metadata), so there
is no more whole-document truncation. Subagent lifecycle and every Bedrock
exchange stream to the AG-UI event bus and are written to the run log file.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from app.agents.claims_orchestrator.document_understanding import build_full_document_model
from app.agents.claims_orchestrator.section_scope import TARGET_SECTION, match_sources_for_unit
from app.agents.claims_orchestrator.source_survey import survey_all_sources
from app.config import MOCK_RUNS_ENABLED
from app.control_plane.run_state import RunState
from app.schemas.claim import Claim, ClaimStatus, ClaimType, ScopedValue
from app.schemas.evidence_hint import EpistemicStatus, EvidenceHint, HintFact, VerificationPlan
from app.schemas.section import DocumentLocator
from app.services.bedrock import invoke_bedrock, parse_bedrock_json
from app.services.database import default_claim_repo, default_run_repo
from app.services.event_stream import default_broker
from app.services.logging_config import get_run_logger, log_bedrock_exchange
from app.services.storage import default_storage
from app.tools.artifact_tools import publish_artifact

_VALID_CLAIM_TYPES = {t.value for t in ClaimType}
_QUANTITATIVE = _VALID_CLAIM_TYPES - {
    ClaimType.narrative_fact.value,
    ClaimType.reconciliation.value,
    ClaimType.other.value,
}


# --------------------------------------------------------------------------- #
# Input resolution
# --------------------------------------------------------------------------- #
def _resolve_target_path(run: dict[str, Any], run_id: str) -> Path:
    target_obj_id = run.get("target_object_id")
    if target_obj_id and Path(target_obj_id).is_file():
        return Path(target_obj_id).resolve()

    cand = default_storage.root_dir / "default" / run_id / "input" / "target"
    if cand.exists():
        files = list(cand.glob("*.docx"))
        if files:
            return files[0].resolve()

    if MOCK_RUNS_ENABLED:
        sample = Path("runtime/sample_pbrer_data/PBRER_Annual_Report_2024_Nexipril.docx").resolve()
        if sample.exists():
            return sample
    raise FileNotFoundError(f"Target document not found for run {run_id}")


def _resolve_source_files(run: dict[str, Any], run_id: str) -> list[Path]:
    source_obj_ids = run.get("source_object_ids", [])
    source_files = [Path(s).resolve() for s in source_obj_ids if Path(s).is_file()]

    if not MOCK_RUNS_ENABLED and len(source_files) != len(source_obj_ids):
        raise FileNotFoundError(f"One or more attached source files are missing for run {run_id}")

    if not source_files:
        src_cand = default_storage.root_dir / "default" / run_id / "input" / "sources"
        if src_cand.exists():
            source_files = list(src_cand.glob("*.xlsx")) + list(src_cand.glob("*.csv"))
    if not source_files and MOCK_RUNS_ENABLED:
        sample_dir = Path("runtime/sample_pbrer_data").resolve()
        if sample_dir.exists():
            source_files = list(sample_dir.glob("*.xlsx"))
    if not source_files:
        raise FileNotFoundError(f"No XLSX/CSV source files found for run {run_id}")
    return source_files


def _clear_derived_outputs(run_id: str) -> None:
    """Remove prior extraction/stage-1 outputs so a rerun writes cleanly."""
    base = default_storage.root_dir / "default" / run_id
    for sub in ("extracted", "stage_1_claims"):
        target = base / sub
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Claim coercion (resilient mapping of model output -> validated Claim)
# --------------------------------------------------------------------------- #
def _scoped(raw: Any) -> ScopedValue:
    d = raw if isinstance(raw, dict) else {}
    status = d.get("evidence_status", "unknown")
    if status not in ("observed", "inferred", "unknown"):
        status = "unknown"
    value = d.get("value")
    return ScopedValue(value=str(value) if value is not None else None, evidence_status=EpistemicStatus(status))


def _facts(items: Any, status: EpistemicStatus) -> list[HintFact]:
    out: list[HintFact] = []
    for it in items or []:
        if isinstance(it, dict):
            statement = str(it.get("statement", "")).strip()
            refs = [str(r) for r in (it.get("source_refs") or [])]
        else:
            statement, refs = str(it).strip(), []
        if statement:
            out.append(HintFact(statement=statement, status=status, source_refs=refs))
    return out


def _verification_plan(raw: Any) -> VerificationPlan | None:
    d = raw if isinstance(raw, dict) else None
    if not d:
        return None
    def _s(key: str) -> str | None:
        v = d.get(key)
        return str(v) if v not in (None, "") else None
    def _list(key: str) -> list[str]:
        v = d.get(key)
        if isinstance(v, list):
            return [str(x) for x in v if x not in (None, "")]
        return [str(v)] if v not in (None, "") else []
    hri = d.get("header_row_index")
    try:
        hri = int(hri) if hri is not None else None
    except (TypeError, ValueError):
        hri = None
    return VerificationPlan(
        source_file=_s("source_file"),
        sheet=_s("sheet"),
        header_row_index=hri,
        columns=_list("columns"),
        filters=_list("filters"),
        dedup_key=_s("dedup_key"),
        aggregation=_s("aggregation"),
        expected_value=_s("expected_value"),
        notes=_s("notes"),
    )


def _evidence_hint(raw: Any, normalized: str, fallback_refs: list[str], plan: VerificationPlan | None) -> EvidenceHint:
    d = raw if isinstance(raw, dict) else {}
    text = str(d.get("text") or "").strip() or (normalized[:300] if normalized else "Evidence hint pending reviewer confirmation.")
    return EvidenceHint(
        text=text[:1200],
        observed=_facts(d.get("observed"), EpistemicStatus.observed),
        inferred=_facts(d.get("inferred"), EpistemicStatus.inferred),
        unknowns=[str(u) for u in (d.get("unknowns") or [])],
        source_refs=[str(r) for r in (d.get("source_refs") or fallback_refs)],
        verification_plan=plan,
    )


def _coerce_claim(
    item: dict[str, Any],
    seq: int,
    unit: dict[str, Any],
    block_index: dict[str, dict[str, Any]],
    doc_filename: str,
    matched_filenames: list[str],
) -> Claim:
    block = block_index.get(str(item.get("block_id", "")))
    if block is None:
        block = unit["blocks"][0] if unit["blocks"] else None

    locator = DocumentLocator(
        document_id=doc_filename,
        block_id=block.get("block_id") if block else None,
        paragraph_index=block.get("paragraph_index") if block else None,
        table_index=block.get("table_index") if block else None,
    )

    claim_type = str(item.get("claim_type", "other"))
    if claim_type not in _VALID_CLAIM_TYPES:
        claim_type = "other"

    entity_unit = item.get("entity_unit") or None
    derivation = None
    if claim_type in _QUANTITATIVE and not entity_unit:
        derivation = {
            "decision": "needs_human_review",
            "reason": "Extractor did not provide entity_unit for a quantitative claim.",
        }

    normalized = str(item.get("normalized_statement") or item.get("raw_statement") or "").strip()
    reported_value = item.get("reported_value")
    if isinstance(reported_value, (list, dict)):
        reported_value = None

    plan = _verification_plan(item.get("verification_plan"))

    return Claim.model_validate({
        "claim_id": f"CLM-{seq:04d}",
        "section_id": unit["section_id"],
        "section_number": unit["section_number"],
        "raw_statement": str(item.get("raw_statement") or normalized or unit["title"])[:4000],
        "normalized_statement": (normalized or str(item.get("raw_statement") or unit["title"]))[:4000],
        "claim_type": claim_type,
        "entity_unit": entity_unit,
        "reported_value": reported_value,
        "unit": item.get("unit"),
        "numerator": item.get("numerator"),
        "denominator": item.get("denominator"),
        "reporting_period": _scoped(item.get("reporting_period")).model_dump(),
        "population": _scoped(item.get("population")).model_dump(),
        "target_locator": locator.model_dump(),
        "evidence_hint": _evidence_hint(item.get("evidence_hint"), normalized, matched_filenames, plan).model_dump(),
        "derivation": derivation,
        "status": ClaimStatus.hinted.value,
    })


# --------------------------------------------------------------------------- #
# Subagent extraction
# --------------------------------------------------------------------------- #
def build_source_map(source_knowledge: dict[str, Any], matched_filenames: list[str]) -> list[dict[str, Any]]:
    """Compact, executable map of the matched data sheets.

    For each sheet: file, sheet name, header row offset, row count, the counts
    stated in the sheet preamble, candidate keys, and every real column with its
    type plus — for categorical columns — the exact set of values usable as filters.
    """
    matched = set(matched_filenames)
    filename_by_source = {
        s["source_id"]: s["original_filename"] for s in source_knowledge.get("sources", [])
    }
    sheets: list[dict[str, Any]] = []
    for d in source_knowledge.get("datasets", []):
        fname = filename_by_source.get(d.get("source_id"))
        if fname not in matched:
            continue
        cols: list[dict[str, Any]] = []
        for p in d.get("column_profiles", []):
            entry: dict[str, Any] = {"name": p.get("name"), "type": p.get("type")}
            if p.get("is_categorical") and p.get("distinct_values"):
                entry["values"] = p["distinct_values"]
            elif p.get("example_values"):
                entry["examples"] = p["example_values"][:4]
            cols.append(entry)
        sheets.append({
            "source_file": fname,
            "sheet": d.get("sheet_or_table"),
            "header_row_index": d.get("header_row_index", 0),
            "row_count": d.get("row_count"),
            "stated_in_sheet": (d.get("preamble") or [])[:4],
            "candidate_keys": d.get("candidate_key_columns", []),
            "columns": cols,
        })
    return sheets


def _unit_blocks_payload(unit: dict[str, Any]) -> list[dict[str, Any]]:
    payload = []
    for b in unit["blocks"]:
        if b.get("type") == "table":
            payload.append({
                "block_id": b["block_id"],
                "type": "table",
                "headers": b.get("headers", []),
                "rows": (b.get("rows") or [])[:25],
            })
        else:
            payload.append({
                "block_id": b["block_id"],
                "type": "paragraph",
                "text": b.get("text", ""),
            })
    return payload


def _is_numeric(value: Any) -> bool:
    if value is None:
        return False
    try:
        float(str(value).replace(",", "").replace("%", "").strip())
        return True
    except (TypeError, ValueError):
        return False


def _extract_claims_for_unit(
    unit: dict[str, Any],
    source_knowledge: dict[str, Any],
    matched_filenames: list[str],
    doc_filename: str,
    start_seq: int,
    logger: Any,
) -> list[Claim]:
    source_map = build_source_map(source_knowledge, matched_filenames)
    blocks_payload = _unit_blocks_payload(unit)

    prompt = f"""You are a pharmacovigilance reconciliation analyst working ONLY on PBRER
Section {unit['section_number']} — "{unit['title']}".

GOAL: extract ONLY NUMERIC, INDEPENDENTLY VERIFIABLE claims that can be reproduced by
counting/aggregating rows in the SOURCE_DATA_MAP below. Each claim is a number the report
states about this risk (e.g. number of cases, serious cases, fatal/outcome cases, events,
cases by seriousness/source split, a rate). For each claim you MUST provide a concrete
verification_plan that names the exact sheet, columns, filter values, dedup key and
aggregation — drawn from the SOURCE_DATA_MAP so the Rules agent can locate the rows.

STRICT EXCLUSIONS — do NOT emit a claim for:
- regulatory/narrative history, PRAC recommendations, RMP version numbers, document ids,
  dates, or anything citing a document NOT present in RELEVANT_SOURCE_FILES;
- qualitative conclusions ("no new information", "remains an identified risk");
- any statement with no number that maps to the source data.
If the subsection has no such numeric claim, return an empty claims array. Never invent
columns, filter values, counts, or sources; use only names/values present in SOURCE_DATA_MAP.

For each claim return an object with:
- block_id: the id of the SUBSECTION_BLOCK the claim comes from
- raw_statement: the exact sentence/phrase as written
- normalized_statement: a precise one-sentence restatement
- claim_type: one of distinct_case_count, event_count, patient_count, subject_count,
  source_split, term_frequency, rate, exposure, reconciliation
- entity_unit: the counted entity ("case", "event", "patient", ...) — REQUIRED
- reported_value: the numeric value stated in the report (number); unit; numerator; denominator
- reporting_period and population: each {{"value": string|null, "evidence_status": "observed"|"inferred"|"unknown"}}
- evidence_hint: {{"text": string, "observed": [{{"statement": string, "source_refs": [filename]}}],
  "inferred": [{{"statement": string, "source_refs": [filename]}}], "unknowns": [string], "source_refs": [filename]}}
- verification_plan: {{"source_file": string, "sheet": string, "header_row_index": int,
  "columns": [exact column names used], "filters": ["Column == 'Value'", ...] using EXACT values
  from the map, "dedup_key": column (e.g. "Case Number"), "aggregation": e.g. "distinct count of Case Number",
  "expected_value": the reported value as string, "notes": any assumption the Rules agent must resolve}}

Return ONLY a JSON object: {{"claims": [ ... ]}} with no markdown or commentary.

RELEVANT_SOURCE_FILES:
{json.dumps(matched_filenames, ensure_ascii=False)}

SOURCE_DATA_MAP (real sheets, header row offsets, columns, and exact categorical filter values):
{json.dumps(source_map, ensure_ascii=False)}

SUBSECTION_BLOCKS:
{json.dumps(blocks_payload, ensure_ascii=False)}
"""

    label = f"claims:{unit['section_number']}"
    try:
        raw_response = invoke_bedrock(prompt, max_tokens=8192)
    except Exception as exc:
        log_bedrock_exchange(logger, label, prompt, error=exc)
        raise
    log_bedrock_exchange(logger, label, prompt, response=raw_response)

    parsed = parse_bedrock_json(raw_response)
    if isinstance(parsed, list):
        parsed = {"claims": parsed}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("claims"), list):
        raise ValueError(
            f"Bedrock response for Section {unit['section_number']} did not contain a claims array"
        )

    block_index = {b["block_id"]: b for b in unit["blocks"]}
    claims: list[Claim] = []
    dropped = 0
    seq = start_seq
    for item in parsed["claims"]:
        if not isinstance(item, dict):
            continue
        try:
            claim = _coerce_claim(item, seq, unit, block_index, doc_filename, matched_filenames)
        except Exception as exc:
            logger.warning("Skipping invalid claim in %s: %s", unit["section_number"], exc)
            continue
        # Numeric-only safety net: keep quantitative/reconciliation claims or any
        # claim carrying a numeric value; drop pure narrative/qualitative items.
        keep_types = _QUANTITATIVE | {ClaimType.reconciliation.value}
        if claim.claim_type.value not in keep_types and not _is_numeric(claim.reported_value):
            dropped += 1
            continue
        claims.append(claim)
        seq += 1
    if dropped:
        logger.info("Section %s: dropped %d non-numeric/narrative claim(s)", unit["section_number"], dropped)
    return claims


def _mock_unit_claims(
    unit: dict[str, Any],
    matched_filenames: list[str],
    doc_filename: str,
    start_seq: int,
) -> list[Claim]:
    """Deterministic claims for offline mode so the 16.3 flow is demonstrable without Bedrock."""
    claims: list[Claim] = []
    seq = start_seq
    paras = [b for b in unit["blocks"] if b.get("type") != "table" and len(b.get("text", "")) > 40]
    for b in paras[:3]:
        text = b["text"]
        claim_type = ClaimType.narrative_fact
        claims.append(Claim(
            claim_id=f"CLM-{seq:04d}",
            section_id=unit["section_id"],
            section_number=unit["section_number"],
            raw_statement=text[:600],
            normalized_statement=text[:300],
            claim_type=claim_type,
            target_locator=DocumentLocator(
                document_id=doc_filename,
                block_id=b["block_id"],
                paragraph_index=b.get("paragraph_index"),
            ),
            evidence_hint=EvidenceHint(
                text=f"Verify against {', '.join(matched_filenames[:2]) or 'uploaded sources'}.",
                source_refs=matched_filenames,
            ),
            status=ClaimStatus.hinted,
        ))
        seq += 1
    return claims


# --------------------------------------------------------------------------- #
# Stage orchestration
# --------------------------------------------------------------------------- #
def run_claims_stage(run_id: str, frozen_input_manifest: str | None = None) -> dict[str, Any]:
    """Execute Stage 1 scoped to Section 16.3 with one subagent per subsection."""
    logger = get_run_logger(run_id, "claims")
    logger.info("=== Stage 1 (Claims) START | run=%s | mock=%s ===", run_id, MOCK_RUNS_ENABLED)

    run = default_run_repo.get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    _clear_derived_outputs(run_id)

    default_broker.emit_stage_update(run_id, "claims", "running", progress=5)
    default_broker.emit_activity(
        run_id=run_id, stage="claims", title="Claims Orchestrator started",
        detail="Focusing on PBRER Section 16.3 — building document model.",
        kind="agent", agent="claims-orchestrator",
    )

    cur = default_run_repo.get_run(run_id)
    if cur["status"] == RunState.READY_FOR_STAGE_1.value:
        default_run_repo.transition(
            run_id=run_id, expected_version=cur["version"],
            new_state=RunState.CLAIMS_RUNNING, active_stage="claims",
        )

    # 1. Document understanding + 16.3 scoping
    target_path = _resolve_target_path(run, run_id)
    logger.info("Target document: %s", target_path)
    default_broker.emit_activity(
        run_id=run_id, stage="claims", title="Extracting target document",
        detail=f"Parsing {target_path.name} structure and locators", kind="tool", source=target_path.name,
    )
    doc_data = build_full_document_model(target_path, run_id)
    scope = doc_data["scope"]
    units = scope["work_units"]
    doc_filename = doc_data["filename"]
    logger.info(
        "Scoped to Section %s: %d subtree sections, %d blocks, %d work units: %s",
        TARGET_SECTION, len(scope["subtree_sections"]), len(scope["scoped_blocks"]),
        len(units), [u["section_number"] for u in units],
    )
    default_broker.emit_activity(
        run_id=run_id, stage="claims", title="Scoped to Section 16.3",
        detail=f"{len(units)} leaf subsections, {len(scope['scoped_blocks'])} blocks in scope.",
        kind="agent", agent="claims-orchestrator",
    )
    default_broker.emit_stage_update(run_id, "claims", "running", progress=20)

    # 2. Source survey
    source_files = _resolve_source_files(run, run_id)
    logger.info("Source files: %s", [p.name for p in source_files])
    default_broker.emit_activity(
        run_id=run_id, stage="claims", title="Surveying sources",
        detail=f"Profiling {len(source_files)} uploaded source workbooks", kind="tool",
    )
    source_knowledge = survey_all_sources(run_id, source_files)
    default_broker.emit_stage_update(run_id, "claims", "running", progress=35)

    # 3. One claim-extraction subagent per 16.3 subsection
    claims: list[Claim] = []
    unit_errors: list[str] = []
    total = len(units) or 1
    for i, unit in enumerate(units):
        sub_id = f"claims-{unit['section_number'].replace('.', '-')}"
        name = f"{unit['section_number']} {unit['title'][:48]}"
        matched = match_sources_for_unit(unit, source_knowledge["sources"])

        default_broker.emit_subagent_start(
            run_id, "claims", sub_id, name, "claim-extraction",
            detail=f"{len(unit['blocks'])} blocks · sources: {', '.join(matched[:3]) or 'none'}",
        )
        default_broker.emit_activity(
            run_id=run_id, stage="claims", title=f"Subagent dispatched · {unit['section_number']}",
            detail=f"{unit['title'][:70]} · {len(unit['blocks'])} blocks · scoped source access",
            kind="agent", agent=name, status="running",
        )
        default_broker.emit_tool_call(
            run_id, "read_subsection_blocks",
            {"section": unit["section_number"], "blocks": len(unit["blocks"])},
            {"matched_sources": matched},
        )
        logger.info("Subagent %s START | section=%s | blocks=%d | sources=%s",
                    sub_id, unit["section_number"], len(unit["blocks"]), matched)

        try:
            if MOCK_RUNS_ENABLED:
                unit_claims = _mock_unit_claims(unit, matched, doc_filename, start_seq=len(claims) + 1)
            else:
                unit_claims = _extract_claims_for_unit(
                    unit, source_knowledge, matched, doc_filename, start_seq=len(claims) + 1, logger=logger,
                )
            claims.extend(unit_claims)
            for c in unit_claims:
                default_broker.emit_claim_update(run_id, c.claim_id, c.section_id, c.status.value)
            default_broker.emit_subagent_finish(
                run_id, "claims", sub_id, name, claims=len(unit_claims),
                detail=f"{len(unit_claims)} claim(s) extracted",
            )
            default_broker.emit_activity(
                run_id=run_id, stage="claims", title=f"Subagent complete · {unit['section_number']}",
                detail=f"{len(unit_claims)} claim(s) extracted from {unit['title'][:60]}",
                kind="agent", agent=name, status="done",
            )
            logger.info("Subagent %s DONE | %d claims", sub_id, len(unit_claims))
        except Exception as exc:  # resilient: one bad subsection must not sink the stage
            unit_errors.append(f"{unit['section_number']}: {exc}")
            logger.exception("Subagent %s FAILED", sub_id)
            default_broker.emit_subagent_error(run_id, "claims", sub_id, name, str(exc))
            default_broker.emit_activity(
                run_id=run_id, stage="claims", title=f"Subagent error · {unit['section_number']}",
                detail=str(exc)[:200], kind="warning", status="error",
            )

        default_broker.emit_stage_update(run_id, "claims", "running", progress=35 + int(55 * ((i + 1) / total)))

    if not claims:
        detail = "No verifiable claims were extracted from Section 16.3."
        if unit_errors:
            detail += f" {len(unit_errors)} subagent(s) errored — see the run log file."
        logger.error("%s | errors=%s", detail, unit_errors)
        raise ValueError(detail)

    logger.info("Total claims extracted: %d across %d subsections (%d subagent errors)",
                len(claims), len(units), len(unit_errors))

    # 4. Persist into the Claim Registry
    saved_claims = []
    for c in claims:
        saved_claims.append(default_claim_repo.save_claim(run_id, c.model_dump()))

    # 5. Publish Stage 1 artifacts
    claims_register_json = json.dumps([c.model_dump() for c in claims], indent=2)
    default_storage.put_derived(
        tenant_id="default", run_id=run_id,
        logical_path="stage_1_claims/claims_register.v001.json", body=claims_register_json,
    )

    artifacts_to_publish = [
        ("stage_1_claims/source_knowledge.md", "text/markdown"),
        ("stage_1_claims/source_knowledge.json", "application/json"),
        ("stage_1_claims/knowledge_graph.json", "application/json"),
        ("stage_1_claims/schema_profiles.json", "application/json"),
        ("stage_1_claims/relationships.json", "application/json"),
        ("stage_1_claims/claims_register.v001.json", "application/json"),
    ]
    manifest_entries = []
    hasher = hashlib.sha256()
    for rel_path, media_type in artifacts_to_publish:
        content = default_storage.read_text(f"default/{run_id}/{rel_path}")
        hasher.update(content.encode("utf-8"))
        entry = publish_artifact(
            run_id=run_id, stage="claims", claim_id=None, logical_path=rel_path,
            media_type=media_type, content=content, producer_agent_id="claims-orchestrator",
        )
        manifest_entries.append(entry)
        default_broker.emit_artifact_update(
            run_id=run_id, artifact_id=entry["artifact_id"], logical_path=entry["logical_path"],
            version=entry["version"], sha256=entry["sha256"],
        )

    stage_1_manifest_hash = hasher.hexdigest()
    default_run_repo.set_manifest_hash(run_id, "claims", stage_1_manifest_hash)

    # 6. Transition to CLAIMS_AWAITING_REVIEW
    current_run = default_run_repo.get_run(run_id)
    default_run_repo.transition(
        run_id=run_id, expected_version=current_run["version"],
        new_state=RunState.CLAIMS_AWAITING_REVIEW, active_stage=None,
    )

    default_broker.emit_stage_update(run_id, "claims", "review", progress=100)
    default_broker.emit_activity(
        run_id=run_id, stage="claims", title="Stage 1 complete: Awaiting Review",
        detail=f"Extracted {len(saved_claims)} claims from Section 16.3. Manifest: {stage_1_manifest_hash[:12]}...",
        kind="gate", status="done",
    )
    logger.info("=== Stage 1 COMPLETE | %d claims | manifest=%s ===", len(saved_claims), stage_1_manifest_hash[:12])

    return {
        "status": "CLAIMS_AWAITING_REVIEW",
        "stage_1_manifest_hash": stage_1_manifest_hash,
        "total_claims": len(saved_claims),
        "subagents": len(units),
        "subagent_errors": unit_errors,
        "claims": saved_claims,
    }
