from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class ValidationCheck(BaseModel):
    name: str
    passed: bool
    details: str
    severity: str = "error"  # error, warning, info


class ValidationResult(BaseModel):
    claim_id: str
    attempt: int = 1
    status: str = "VALIDATED"  # VALIDATED, RETRY_NEEDED, UNRESOLVED
    checks: list[ValidationCheck] = Field(default_factory=list)
    reconciled: bool = True
    discrepancy: str | None = None
    target_stage_for_retry: str | None = None  # claims, evidence, rule_engineer, human
    feedback_message: str | None = None
    audit_trail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

