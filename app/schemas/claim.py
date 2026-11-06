from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class Claim(BaseModel):
    claim_id: str
    section_id: str
    section_number: str
    raw_text: str
    normalized_statement: str
    claim_type: str = "statement"  # total_cases, source_split, preferred_term, rate, narrative
    reported_value: str | None = None
    numeric_value: float | None = None
    unit: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    reporting_period: dict[str, Any] | None = None
    target_locator: dict[str, Any] = Field(default_factory=dict)
    extraction_confidence: float = 1.0
    status: str = "PENDING"  # PENDING, EVIDENCE_FOUND, RULE_DRAFTED, RULE_EXECUTED, VALIDATED, UNRESOLVED
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    rule: dict[str, Any] | None = None
    calculation_result: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    attempts: int = 0
    assigned_agent: str | None = None
    user_guidance: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

