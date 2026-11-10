"""Strands @tool definitions for Stage 1 hierarchical Claim Registration."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from strands import tool

from app.schemas.claim import (
    ChildClaim,
    Claim,
    ClaimStatus,
    ClaimType,
    ParentClaim,
)
from app.schemas.evidence_hint import EpistemicStatus, EvidenceHint, HintFact, VerificationPlan
from app.schemas.section import DocumentLocator
from app.services.database import default_claim_repo
from app.services.event_stream import default_broker


def _resolve_claim_type(raw: str) -> ClaimType:
    cleaned = (raw or "").strip().lower().replace(" ", "_")
    try:
        return ClaimType(cleaned)
    except ValueError:
        aliases = {
            "count": ClaimType.distinct_case_count,
            "case_count": ClaimType.distinct_case_count,
            "percentage": ClaimType.rate,
            "proportion": ClaimType.rate,
            "percent": ClaimType.rate,
        }
        return aliases.get(cleaned, ClaimType.distinct_case_count)


@dataclass
class ClaimToolsetContext:
    run_id: str
    target_filename: str
    sections_by_number: dict[str, dict[str, Any]]
    uploaded_filenames: list[str]
    per_file_mds: dict[str, str]
    registered_claims: list[dict[str, Any]] = field(default_factory=list)
    _seq: int = 0

    def next_claim_id(self) -> str:
        self._seq += 1
        return f"CLM-{self._seq:04d}"

    def resolve_sources(self, requested: list[str]) -> list[str]:
        if not requested:
            return []
        resolved: list[str] = []
        lower_map = {fn.lower(): fn for fn in self.uploaded_filenames}
        for item in requested:
            item_clean = (item or "").strip()
            if not item_clean:
                continue
            if item_clean in self.uploaded_filenames:
                if item_clean not in resolved:
                    resolved.append(item_clean)
                continue
            low = item_clean.lower()
            if low in lower_map:
                fn = lower_map[low]
                if fn not in resolved:
                    resolved.append(fn)
                continue
            # Substring / stem match against real uploaded filenames
            matches = [fn for fn in self.uploaded_filenames if low in fn.lower() or fn.lower() in low]
            for fn in matches:
                if fn not in resolved:
                    resolved.append(fn)
        return resolved


def create_claim_extraction_tools(ctx: ClaimToolsetContext) -> list[Any]:
    """Build Strands `@tool` callables bound to a single Stage 1 run context."""

    @tool
    def register_claim_group(
        section_number: str,
        parent_statement: str,
        parent_normalized_statement: str,
        parent_claim_type: str,
        parent_entity_unit: str,
        parent_reported_value: str,
        search_criteria: str,
        source_document_mapped: list[str],
        hint_text: str,
        children_claims: list[dict[str, Any]] | None = None,
        parent_unit: str = "cases",
        parent_numerator: str = "",
        parent_denominator: str = "",
        parent_block_id: str = "",
        hint_observed: list[str] | None = None,
        hint_inferred: list[str] | None = None,
        hint_unknowns: list[str] | None = None,
        verification_plan: dict[str, Any] | None = None,
    ) -> str:
        """Validate and register one parent claim + its child sub-claims (children may be empty []).

        Required fields:
        - section_number: e.g. '16.3.1.2'
        - parent_statement, parent_normalized_statement, parent_claim_type, parent_entity_unit, parent_reported_value
        - search_criteria: exact MedDRA terms/SMQs or filtering criteria defining this claim cohort
        - source_document_mapped: non-empty list of uploaded source filenames
        - hint_text: clear verification instructions grounded in the Master Summary
        - children_claims: optional list of child sub-claim objects (can be empty `[]`)
        """
        missing: list[str] = []
        if not (parent_statement or "").strip():
            missing.append("parent_statement")
        if not (parent_normalized_statement or "").strip():
            missing.append("parent_normalized_statement")
        if not (parent_entity_unit or "").strip():
            missing.append("parent_entity_unit")
        if parent_reported_value is None or str(parent_reported_value).strip() == "":
            missing.append("parent_reported_value")
        if not (search_criteria or "").strip():
            missing.append("search_criteria")
        if not (hint_text or "").strip():
            missing.append("hint_text")

        mapped_sources = ctx.resolve_sources(source_document_mapped or [])
        if not mapped_sources:
            missing.append(
                f"source_document_mapped (must match uploaded files: {ctx.uploaded_filenames})"
            )

        if missing:
            return f"VALIDATION_ERROR: Missing or empty required claim fields: {', '.join(missing)}. Fix and call register_claim_group again."

        raw_children = children_claims or []
        validated_children: list[ChildClaim] = []
        claim_id = ctx.next_claim_id()

        for idx, ch in enumerate(raw_children, start=1):
            if not isinstance(ch, dict):
                ctx._seq -= 1
                return f"VALIDATION_ERROR: children_claims[{idx - 1}] must be an object/dict."
            c_stmt = str(ch.get("raw_statement") or "").strip()
            c_val = ch.get("reported_value")
            if not c_stmt or c_val is None or str(c_val).strip() == "":
                ctx._seq -= 1
                return (
                    f"VALIDATION_ERROR: children_claims[{idx - 1}] must define non-empty "
                    "`raw_statement` and `reported_value`."
                )
            validated_children.append(
                ChildClaim(
                    child_claim_id=f"{claim_id}-C{idx}",
                    raw_statement=c_stmt,
                    normalized_statement=str(ch.get("normalized_statement") or c_stmt).strip(),
                    claim_type=_resolve_claim_type(str(ch.get("claim_type") or "distinct_case_count")),
                    entity_unit=str(ch.get("entity_unit") or parent_entity_unit).strip(),
                    reported_value=c_val,
                    unit=ch.get("unit"),
                    numerator=str(ch["numerator"]) if ch.get("numerator") is not None else None,
                    denominator=str(ch["denominator"]) if ch.get("denominator") is not None else None,
                    relationship=str(ch.get("relationship") or "subset_of_parent").strip(),
                    search_criteria=ch.get("search_criteria"),
                    target_locator=DocumentLocator(
                        document_id=ctx.target_filename,
                        block_id=ch.get("block_id") or parent_block_id or None,
                    )
                    if (ch.get("block_id") or parent_block_id)
                    else None,
                )
            )

        sec_meta = ctx.sections_by_number.get(section_number, {})
        sec_id = sec_meta.get("section_id") or f"sec_{section_number.replace('.', '_')}"
        sec_title = sec_meta.get("title") or ""

        locator = DocumentLocator(
            document_id=ctx.target_filename,
            block_id=parent_block_id or None,
        )
        parent_obj = ParentClaim(
            raw_statement=parent_statement.strip(),
            normalized_statement=parent_normalized_statement.strip(),
            claim_type=_resolve_claim_type(parent_claim_type),
            entity_unit=parent_entity_unit.strip(),
            reported_value=parent_reported_value,
            unit=parent_unit or None,
            numerator=parent_numerator or None,
            denominator=parent_denominator or None,
            target_locator=locator,
        )

        vp_model = None
        if isinstance(verification_plan, dict):
            vp_model = VerificationPlan(
                source_file=verification_plan.get("source_file") or mapped_sources[0],
                sheet=verification_plan.get("sheet"),
                header_row_index=verification_plan.get("header_row_index"),
                columns=verification_plan.get("columns") or [],
                filters=verification_plan.get("filters") or [],
                dedup_key=verification_plan.get("dedup_key"),
                aggregation=verification_plan.get("aggregation"),
                expected_value=str(verification_plan.get("expected_value") or parent_reported_value),
                notes=verification_plan.get("notes"),
            )

        hint_obj = EvidenceHint(
            text=hint_text.strip(),
            observed=[
                HintFact(statement=s, status=EpistemicStatus.observed, source_refs=mapped_sources)
                for s in (hint_observed or [])
                if str(s).strip()
            ],
            inferred=[
                HintFact(statement=s, status=EpistemicStatus.inferred, source_refs=mapped_sources)
                for s in (hint_inferred or [])
                if str(s).strip()
            ],
            unknowns=[str(u) for u in (hint_unknowns or []) if str(u).strip()],
            source_refs=mapped_sources,
            verification_plan=vp_model,
        )

        claim = Claim(
            claim_id=claim_id,
            section_id=sec_id,
            section_number=section_number,
            section_title=sec_title,
            parent_claim=parent_obj,
            children_claims=validated_children,
            search_criteria=search_criteria.strip(),
            source_document_mapped=mapped_sources,
            target_locator=locator,
            evidence_hint=hint_obj,
            status=ClaimStatus.hinted,
        )

        saved = default_claim_repo.save_claim(ctx.run_id, claim.model_dump(mode="json"))
        ctx.registered_claims.append(saved)
        default_broker.emit_claim_update(ctx.run_id, saved)
        default_broker.emit_activity(
            run_id=ctx.run_id,
            stage="claims",
            title=f"Registered {claim_id} ({section_number})",
            detail=f"{parent_statement[:90]} · {len(validated_children)} child claim(s)",
            kind="success",
            agent="ClaimExtractorStrands",
        )
        return (
            f"REGISTERED {claim_id} in section {section_number} with "
            f"{len(validated_children)} child claim(s) mapped to {mapped_sources}."
        )

    @tool
    def read_source_summary(source_filename: str) -> str:
        """Read the full detailed .md summary for a specific uploaded source file."""
        resolved = ctx.resolve_sources([source_filename])
        if not resolved:
            return f"Source '{source_filename}' not found. Available sources: {ctx.uploaded_filenames}"
        fn = resolved[0]
        return ctx.per_file_mds.get(fn, f"No detailed markdown found for {fn}.")

    @tool
    def list_registered_claims(section_number: str = "") -> str:
        """List claims already registered in this run (optionally filtered by section_number)."""
        claims = ctx.registered_claims
        if section_number.strip():
            claims = [c for c in claims if c.get("section_number") == section_number.strip()]
        compact = [
            {
                "claim_id": c["claim_id"],
                "section_number": c["section_number"],
                "parent_statement": c["raw_statement"],
                "reported_value": c["reported_value"],
                "children_count": len(c.get("children_claims") or []),
                "source_document_mapped": c.get("source_document_mapped") or [],
            }
            for c in claims
        ]
        return json.dumps(compact, indent=2)

    return [register_claim_group, read_source_summary, list_registered_claims]

