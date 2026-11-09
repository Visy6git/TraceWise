"""Canonical source intelligence / knowledge-graph structures for Stage 1."""
from enum import StrEnum
from pydantic import BaseModel, Field


class EvidenceStatus(StrEnum):
    observed = "observed"
    inferred = "inferred"
    unknown = "unknown"


class SourceObject(BaseModel):
    source_id: str
    original_filename: str
    object_id: str
    sha256: str
    format: str
    size_bytes: int
    extraction_status: str
    limitations: list[str] = Field(default_factory=list)


class DatasetProfile(BaseModel):
    dataset_id: str
    source_id: str
    sheet_or_table: str
    visible: bool = True
    header_row: int | None = None
    metadata_rows: list[int] = Field(default_factory=list)
    row_count: int
    column_count: int
    data_columns: list[str]
    candidate_key_columns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ColumnProfile(BaseModel):
    dataset_id: str
    original_name: str
    normalized_name: str
    inferred_type: str
    null_count: int
    null_fraction: float = Field(ge=0, le=1)
    distinct_count: int | None = None
    min_value: str | None = None
    max_value: str | None = None
    sample_values: list[str] = Field(default_factory=list)


class FilterEvidence(BaseModel):
    filter_expression: str
    status: EvidenceStatus
    source_refs: list[str] = Field(default_factory=list)
    rationale: str


class DatasetRelationship(BaseModel):
    left_dataset_id: str
    right_dataset_id: str
    join_keys: list[str]
    tested_cardinality: str
    overlap_count: int
    unmatched_left_count: int
    unmatched_right_count: int
    duplicate_expansion: int
    evidence_refs: list[str] = Field(default_factory=list)


class SourceKnowledge(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    sources: list[SourceObject]
    datasets: list[DatasetProfile]
    columns: list[ColumnProfile]
    relationships: list[DatasetRelationship]
    filter_evidence: list[FilterEvidence]
    global_limitations: list[str] = Field(default_factory=list)
