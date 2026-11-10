"""Hierarchical Parent + Children Claim schemas for TraceWise."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.evidence_hint import EpistemicStatus, EvidenceHint
from app.schemas.section import DocumentLocator


class ClaimType(StrEnum):
    distinct_case_count = "distinct_case_count"
    event_count = "event_count"
    patient_count = "patient_count"
    subject_count = "subject_count"
    source_split = "source_split"
    term_frequency = "term_frequency"
    rate = "rate"
    exposure = "exposure"
    narrative_fact = "narrative_fact"
    reconciliation = "reconciliation"
    other = "other"


class ClaimStatus(StrEnum):
    draft = "draft"
    hinted = "hinted"
    in_progress = "in_progress"
    verified = "verified"
    discrepancy = "discrepancy"
    failed = "failed"
    needs_review = "needs_review"
    artifact_ready = "artifact_ready"
    unresolved = "unresolved"
    superseded = "superseded"


class ScopedValue(BaseModel):
    value: str | None = None
    evidence_status: EpistemicStatus = EpistemicStatus.unknown
    source_refs: list[str] = Field(default_factory=list)


class Derivation(BaseModel):
    decision: str = Field(
        pattern="^(derived_from_existing_claims|independent_claim|needs_human_review)$"
    )
    parent_claim_ids: list[str] = Field(default_factory=list)
    expression: str | None = None
    rounding_rule: str | None = None
    scope_equivalent: bool | None = None
    reason: str


class ParentClaim(BaseModel):
    """Primary numeric proposition in a section (e.g., 235/500 adverse event cases)."""

    raw_statement: str = Field(min_length=1)
    normalized_statement: str = Field(min_length=1)
    claim_type: ClaimType = ClaimType.distinct_case_count
    entity_unit: str = Field(min_length=1)
    reported_value: str | float | int
    unit: str | None = "cases"
    numerator: str | None = None
    denominator: str | None = None
    target_locator: DocumentLocator | None = None


class ChildClaim(BaseModel):
    """Sub-claim nested under a parent claim (e.g., 15 fatal cases out of 235)."""

    child_claim_id: str = ""
    raw_statement: str = Field(min_length=1)
    normalized_statement: str = ""
    claim_type: ClaimType = ClaimType.distinct_case_count
    entity_unit: str = "cases"
    reported_value: str | float | int
    unit: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    relationship: str = Field(
        default="subset_of_parent",
        description="Relationship to parent claim (e.g. fatal_subset, serious_subset, source_split, pt_breakdown)",
    )
    search_criteria: str | None = None
    target_locator: DocumentLocator | None = None
    verified: bool | None = None
    computed_value: str | float | int | None = None
    verification_notes: str | None = None

    @model_validator(mode="after")
    def populate_normalized(self) -> ChildClaim:
        if not self.normalized_statement:
            self.normalized_statement = self.raw_statement
        return self


class VerificationResult(BaseModel):
    """Stage 2 execution result proving whether parent and children claims match source data."""

    verified: bool = False
    status: str = "pending"
    parent_computed_value: str | float | int | None = None
    parent_reported_value: str | float | int | None = None
    children_results: list[dict[str, Any]] = Field(default_factory=list)
    discrepancy_summary: str | None = None
    script_path: str | None = None
    result_artifact_id: str | None = None
    verified_at: str | None = None


class Claim(BaseModel):
    schema_version: str = "2.0"
    claim_id: str
    section_id: str
    section_number: str
    section_title: str = ""
    parent_claim: ParentClaim | None = None
    children_claims: list[ChildClaim] = Field(default_factory=list)
    search_criteria: str = ""
    source_document_mapped: list[str] = Field(default_factory=list)

    # Flat parent mirrors preserved for tabular querying & backwards compatibility
    raw_statement: str = ""
    normalized_statement: str = ""
    claim_type: ClaimType = ClaimType.distinct_case_count
    entity_unit: str | None = None
    reported_value: str | float | int | None = None
    unit: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    reporting_period: ScopedValue = Field(default_factory=ScopedValue)
    population: ScopedValue = Field(default_factory=ScopedValue)
    subgroup: ScopedValue | None = None
    target_locator: DocumentLocator
    evidence_hint: EvidenceHint
    derivation: Derivation | None = None
    status: ClaimStatus = ClaimStatus.draft
    verification_result: VerificationResult | None = None
    version: int = 1

    @model_validator(mode="after")
    def sync_parent_and_flat_fields(self) -> Claim:
        if self.parent_claim is not None:
            if not self.raw_statement:
                self.raw_statement = self.parent_claim.raw_statement
            if not self.normalized_statement:
                self.normalized_statement = self.parent_claim.normalized_statement
            if self.entity_unit is None:
                self.entity_unit = self.parent_claim.entity_unit
            if self.reported_value is None:
                self.reported_value = self.parent_claim.reported_value
            if self.unit is None:
                self.unit = self.parent_claim.unit
            if self.numerator is None:
                self.numerator = self.parent_claim.numerator
            if self.denominator is None:
                self.denominator = self.parent_claim.denominator
            self.claim_type = self.parent_claim.claim_type
        else:
            self.parent_claim = ParentClaim(
                raw_statement=self.raw_statement or self.normalized_statement or "Unspecified claim",
                normalized_statement=self.normalized_statement or self.raw_statement or "Unspecified claim",
                claim_type=self.claim_type,
                entity_unit=self.entity_unit or "cases",
                reported_value=self.reported_value if self.reported_value is not None else "",
                unit=self.unit,
                numerator=self.numerator,
                denominator=self.denominator,
                target_locator=self.target_locator,
            )

        quantitative = self.claim_type not in {
            ClaimType.narrative_fact,
            ClaimType.reconciliation,
            ClaimType.other,
        }
        if quantitative and not self.entity_unit and not (
            self.derivation and self.derivation.decision == "needs_human_review"
        ):
            raise ValueError(
                "Quantitative claim must define entity_unit or be flagged for human review"
            )
        return self


class ClaimPatch(BaseModel):
    expected_version: int = Field(ge=1)
    raw_statement: str | None = None
    normalized_statement: str | None = None
    reported_value: str | float | int | None = None
    entity_unit: str | None = None
    unit: str | None = None
    search_criteria: str | None = None
    source_document_mapped: list[str] | None = None
    children_claims: list[ChildClaim] | None = None
    reviewer_reason: str = Field(min_length=1, max_length=2000)
