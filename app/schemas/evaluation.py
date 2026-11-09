from enum import StrEnum
from pydantic import BaseModel, Field


class EvaluationStatus(StrEnum):
    PASS = "PASS"
    DISCREPANCY = "DISCREPANCY"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    UNRESOLVED = "UNRESOLVED"


class EvaluationCheck(BaseModel):
    check_id: str
    category: str
    status: str
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    schema_version: str = "1.0"
    claim_id: str
    stage_1_claim_version: int
    stage_2_manifest_hash: str
    status: EvaluationStatus
    checks: list[EvaluationCheck]
    independent_result: str | float | int | None = None
    report_value: str | float | int | None = None
    discrepancy_category: str | None = None
    reviewer_required: bool = False
    evaluated_at: str
