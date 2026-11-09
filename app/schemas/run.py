from enum import StrEnum
from pydantic import BaseModel, Field
from app.schemas.messages import StageName


class RunStatus(StrEnum):
    READY_FOR_STAGE_1 = "READY_FOR_STAGE_1"
    CLAIMS_RUNNING = "CLAIMS_RUNNING"
    CLAIMS_AWAITING_REVIEW = "CLAIMS_AWAITING_REVIEW"
    CLAIMS_APPROVED = "CLAIMS_APPROVED"
    RULES_RUNNING = "RULES_RUNNING"
    RULES_AWAITING_REVIEW = "RULES_AWAITING_REVIEW"
    RULES_APPROVED = "RULES_APPROVED"
    EVALUATION_RUNNING = "EVALUATION_RUNNING"
    EVALUATION_AWAITING_REVIEW = "EVALUATION_AWAITING_REVIEW"
    COMPLETE = "COMPLETE"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class StageStartRequest(BaseModel):
    expected_input_manifest_hash: str = Field(min_length=16)
    idempotency_key: str = Field(min_length=8)


class ReviewDecision(BaseModel):
    decision: str = Field(pattern="^(approve|request_changes)$")
    expected_manifest_hash: str = Field(min_length=16)
    reviewer_note: str | None = Field(default=None, max_length=4000)


class CreateRunRequest(BaseModel):
    run_name: str = Field(min_length=1, max_length=160)
    target_object_id: str
    source_object_ids: list[str] = Field(min_length=1)
    product_name: str | None = None
    reporting_period_start: str | None = None
    reporting_period_end: str | None = None


class RunSummary(BaseModel):
    run_id: str
    run_name: str
    status: RunStatus
    active_stage: StageName | None = None
    input_manifest_hash: str
    created_at: str
    version: int = 1


class StageActionResponse(BaseModel):
    run_id: str
    stage: StageName
    status: str
    attempt_id: str | None = None
    accepted: bool = False
    message: str
