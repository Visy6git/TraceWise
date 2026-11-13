"""Versioned, reusable specification for reproducing PBRER Section 16.3.

This is a domain contract, not a free-form agent summary. Stage 3 is expected to
populate it from reviewer-approved Stage 1/2 artifacts. Unknown rationale and
unverified mappings must remain explicitly unknown; they must never be guessed.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field, model_validator


class KnowledgeState(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class BlueprintStatus(StrEnum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class LogicalField(BaseModel):
    logical_name: str
    meaning: str
    physical_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    data_type: str | None = None
    required: bool = True
    mapping_state: KnowledgeState = KnowledgeState.UNKNOWN
    evidence_refs: list[str] = Field(default_factory=list)


class SourceDatasetContract(BaseModel):
    dataset_id: str
    purpose: str
    source_candidates: list[str] = Field(default_factory=list)
    sheet_candidates: list[str] = Field(default_factory=list)
    fields: list[LogicalField] = Field(default_factory=list)
    entity_key: list[str] = Field(default_factory=list)
    expected_grain: str | None = None
    join_contracts: list[dict[str, Any]] = Field(default_factory=list)
    source_version_policy: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class RetrievalPolicy(BaseModel):
    policy_id: str
    claim_ids: list[str]
    reporting_period_field: str | None = None
    period_semantics: str | None = None
    period_start_expression: str | None = None
    period_end_expression: str | None = None
    as_of_expression: str | None = None
    latest_record_policy: dict[str, Any] = Field(default_factory=dict)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    filter_rationale_state: KnowledgeState = KnowledgeState.UNKNOWN
    evidence_refs: list[str] = Field(default_factory=list)
    human_decisions_required: list[str] = Field(default_factory=list)


class ClaimBlueprint(BaseModel):
    claim_id: str
    section_number: str
    target_locator: dict[str, Any]
    raw_statement: str
    purpose: str
    entity_definition: str
    unit: str
    numerator_logic: dict[str, Any] | None = None
    denominator_logic: dict[str, Any] | None = None
    retrieval_policy_id: str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    transformations: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    render_binding: dict[str, Any] = Field(default_factory=dict)
    methodology_rationale: str | None = None
    rationale_state: KnowledgeState = KnowledgeState.UNKNOWN
    stage_1_claim_version: int | None = None
    stage_2_artifact_refs: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class SectionBlock(BaseModel):
    block_id: str
    section_number: str
    parent_section_number: str | None = None
    order: int
    block_type: str  # heading | narrative | table | claim_binding | note
    title: str | None = None
    text_template: str | None = None
    table_spec: dict[str, Any] | None = None
    claim_bindings: list[str] = Field(default_factory=list)
    source_locator: dict[str, Any] = Field(default_factory=dict)


class BlueprintValidation(BaseModel):
    status: str = "not_run"  # not_run | passed | failed | blocked
    checks: list[dict[str, Any]] = Field(default_factory=list)
    reproduction_tested: bool = False
    executable_present: bool = False
    unresolved_items: list[str] = Field(default_factory=list)
    tested_against_run_id: str | None = None


class SectionReproductionBlueprint(BaseModel):
    schema_version: str = "1.0"
    blueprint_id: str
    version: int = Field(ge=1)
    status: BlueprintStatus = BlueprintStatus.DRAFT
    product_scope: str | None = None
    section_number: str = "16.3"
    source_learning_run_id: str
    source_stage_1_manifest_hash: str
    source_stage_2_manifest_hash: str
    created_at: str
    created_by: str = "Stage3UnderstandingOrchestrator"
    approved_at: str | None = None
    approved_by: str | None = None
    supersedes: str | None = None
    section_structure: list[SectionBlock] = Field(default_factory=list)
    claims: list[ClaimBlueprint] = Field(default_factory=list)
    datasets: list[SourceDatasetContract] = Field(default_factory=list)
    retrieval_policies: list[RetrievalPolicy] = Field(default_factory=list)
    transformation_graph: dict[str, Any] = Field(default_factory=dict)
    narrative_templates: list[dict[str, Any]] = Field(default_factory=list)
    render_spec: dict[str, Any] = Field(default_factory=dict)
    schema_drift_policy: dict[str, Any] = Field(default_factory=dict)
    reproducibility_contract: dict[str, Any] = Field(default_factory=dict)
    validation: BlueprintValidation = Field(default_factory=BlueprintValidation)
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    artifact_refs: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_unique_ids_and_references(self) -> "SectionReproductionBlueprint":
        claim_ids = [c.claim_id for c in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Blueprint claim_id values must be unique")
        dataset_ids = {d.dataset_id for d in self.datasets}
        for claim in self.claims:
            unknown = set(claim.dataset_ids) - dataset_ids
            if unknown:
                raise ValueError(f"Claim {claim.claim_id} references unknown datasets: {sorted(unknown)}")
        policy_ids = {p.policy_id for p in self.retrieval_policies}
        for claim in self.claims:
            if claim.retrieval_policy_id and claim.retrieval_policy_id not in policy_ids:
                raise ValueError(f"Claim {claim.claim_id} references unknown retrieval policy")
        return self
