from pydantic import BaseModel, Field
from typing import Any


class SourceSliceRef(BaseModel):
    source_id: str
    source_hash: str
    dataset_id: str
    sheet_or_table: str
    row_refs: list[str] = Field(default_factory=list)
    column_refs: list[str] = Field(default_factory=list)
    predicate_refs: list[str] = Field(default_factory=list)


class JoinEvidence(BaseModel):
    left_dataset_id: str
    right_dataset_id: str
    keys: list[str]
    tested_cardinality: str
    left_rows: int
    right_rows: int
    matched_rows: int
    unmatched_left: int
    unmatched_right: int
    duplicate_expansion: int
    accepted: bool
    rationale: str


class EvidenceBundle(BaseModel):
    schema_version: str = "1.0"
    claim_id: str
    stage_1_claim_version: int
    sources: list[SourceSliceRef]
    joins: list[JoinEvidence] = Field(default_factory=list)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    row_counts: dict[str, int] = Field(default_factory=dict)
    lineage_digest: str
    unresolved_questions: list[str] = Field(default_factory=list)
