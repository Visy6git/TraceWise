from enum import StrEnum
from pydantic import BaseModel, Field


class ArtifactStatus(StrEnum):
    building = "building"
    ready = "ready"
    review = "review"
    approved = "approved"
    superseded = "superseded"


class ArtifactManifest(BaseModel):
    artifact_id: str
    run_id: str
    stage: str
    claim_id: str | None = None
    logical_path: str
    version: int
    sha256: str
    media_type: str
    size_bytes: int
    producer_agent_id: str
    created_at: str
    status: ArtifactStatus


class RuleSpec(BaseModel):
    schema_version: str = "1.0"
    claim_id: str
    entity_definition: str
    datasets: list[str]
    joins: list[dict]
    filters: list[dict]
    deduplication_key: list[str] = Field(default_factory=list)
    aggregation: dict
    numerator: dict | None = None
    denominator: dict | None = None
    assumptions: list[str] = Field(default_factory=list)


class RuleArtifactBundle(BaseModel):
    claim_id: str
    plan_path: str
    evidence_bundle: str
    rule_spec: RuleSpec
    python_path: str
    tests_path: str
    environment_lock_path: str
    execution_path: str
    result_path: str
    provenance_path: str
    tool_history_path: str
    manifest_path: str
