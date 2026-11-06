from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class EvidenceRecord(BaseModel):
    source_filename: str
    sheet_name: str = ""
    excel_row: int | None = None
    cell_reference: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    matched_terms: list[str] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    claim_id: str
    candidate_datasets: list[str] = Field(default_factory=list)
    relevant_columns: list[str] = Field(default_factory=list)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    joins: list[dict[str, Any]] = Field(default_factory=list)
    sample_records: list[dict[str, Any]] = Field(default_factory=list)
    provenance_rows: list[int] = Field(default_factory=list)
    total_matching_rows: int = 0
    query_syntax: str = ""
    assumptions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

