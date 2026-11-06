from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class MetricFilter(BaseModel):
    column: str
    operator: str = "eq"  # eq, in, contains, gte, lte, between, is_not_null, is_null
    value: Any = None


class MetricJoin(BaseModel):
    left_table: str
    right_table: str
    left_on: str
    right_on: str
    join_type: str = "inner"  # inner, left
    cardinality: str = "many_to_one"  # verified by Explorer


class MetricRule(BaseModel):
    rule_id: str
    claim_id: str
    version: int = 1
    name: str = "Metric Calculation Rule"
    source_table: str
    entity_identifier: str
    aggregation: str = "distinct_count"  # distinct_count, count, sum, average
    joins: list[MetricJoin] = Field(default_factory=list)
    filters: list[MetricFilter] = Field(default_factory=list)
    numerator_filter: list[MetricFilter] = Field(default_factory=list)
    denominator_filter: list[MetricFilter] = Field(default_factory=list)
    output_unit: str = "cases"
    rounding: int | None = None
    assumptions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    status: str = "drafted"  # drafted, executed, validated, rejected

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class MetricResult(BaseModel):
    computed_value: float | int | str
    numeric_value: float | None = None
    numerator: int | float | None = None
    denominator: int | float | None = None
    distinct_entities: int = 0
    executed_sql: str = ""
    execution_ms: float = 0.0
    evidence_row_count: int = 0
    provenance_samples: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "success"  # success, error
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

