from enum import StrEnum
from pydantic import BaseModel, Field, model_validator
from app.schemas.evidence_hint import EvidenceHint, EpistemicStatus
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
    artifact_ready = "artifact_ready"
    unresolved = "unresolved"
    superseded = "superseded"


class ScopedValue(BaseModel):
    value: str | None = None
    evidence_status: EpistemicStatus = EpistemicStatus.unknown
    source_refs: list[str] = Field(default_factory=list)


class Derivation(BaseModel):
    decision: str = Field(pattern="^(derived_from_existing_claims|independent_claim|needs_human_review)$")
    parent_claim_ids: list[str] = Field(default_factory=list)
    expression: str | None = None
    rounding_rule: str | None = None
    scope_equivalent: bool | None = None
    reason: str


class Claim(BaseModel):
    schema_version: str = "1.0"
    claim_id: str
    section_id: str
    section_number: str
    raw_statement: str
    normalized_statement: str
    claim_type: ClaimType
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
    version: int = 1

    @model_validator(mode="after")
    def quantitative_claim_has_entity_or_is_flagged(self):
        quantitative = self.claim_type not in {ClaimType.narrative_fact, ClaimType.reconciliation, ClaimType.other}
        if quantitative and not self.entity_unit and not (self.derivation and self.derivation.decision == "needs_human_review"):
            raise ValueError("Quantitative claim must define entity_unit or be explicitly flagged for human review")
        return self


class ClaimPatch(BaseModel):
    expected_version: int = Field(ge=1)
    raw_statement: str | None = None
    normalized_statement: str | None = None
    reported_value: str | float | int | None = None
    entity_unit: str | None = None
    unit: str | None = None
    reviewer_reason: str = Field(min_length=1, max_length=2000)
