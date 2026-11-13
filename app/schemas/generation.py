"""Contracts for a future-year Section 16.3 generation run.

A generation run is deliberately NOT a Stage 1/2/3 learning run. It references
an immutable approved blueprint version and owns a separate immutable source
snapshot, execution workspace, outputs and audit trail.
"""
from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, Field


class GenerationStatus(StrEnum):
    CREATED = "created"
    PROFILING = "profiling"
    COMPATIBILITY_REVIEW = "compatibility_review"
    READY = "ready"
    RUNNING = "running"
    OUTPUT_REVIEW = "output_review"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GenerationRequest(BaseModel):
    blueprint_id: str
    blueprint_version: int = Field(ge=1)
    reporting_period_start: str
    reporting_period_end: str
    as_of_date: str | None = None
    run_name: str = Field(min_length=1, max_length=160)


class SchemaDriftItem(BaseModel):
    code: str
    severity: str  # info | warning | blocking
    dataset_id: str | None = None
    file_name: str | None = None
    logical_field: str | None = None
    expected: str | None = None
    observed: str | None = None
    suggested_action: str
    auto_mapping_candidate: str | None = None
    reviewer_required: bool = True


class GenerationCompatibilityReport(BaseModel):
    generation_id: str
    blueprint_id: str
    blueprint_version: int
    status: str  # compatible | compatible_with_warnings | blocked
    source_manifest_hash: str
    source_profiles: list[dict] = Field(default_factory=list)
    mappings: list[dict] = Field(default_factory=list)
    drift: list[SchemaDriftItem] = Field(default_factory=list)
    checked_at: str


class GenerationArtifact(BaseModel):
    artifact_id: str
    generation_id: str
    logical_path: str
    media_type: str
    sha256: str
    size_bytes: int
    status: str = "ready"


class GenerationSummary(BaseModel):
    generation_id: str
    run_name: str
    blueprint_id: str
    blueprint_version: int
    status: GenerationStatus
    reporting_period_start: str
    reporting_period_end: str
    as_of_date: str | None = None
    source_manifest_hash: str
    output_manifest_hash: str | None = None
    compatibility_status: str | None = None
    created_at: str
    version: int = 1
