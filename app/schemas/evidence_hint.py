from enum import StrEnum
from pydantic import BaseModel, Field


class EpistemicStatus(StrEnum):
    observed = "observed"
    inferred = "inferred"
    unknown = "unknown"


class HintFact(BaseModel):
    statement: str
    status: EpistemicStatus
    source_refs: list[str] = Field(default_factory=list)


class VerificationPlan(BaseModel):
    """Concrete, executable recipe the Rules agent follows to reproduce a claim.

    Every field is grounded in the real source map (actual sheet names, header
    row offset, real column names, and exact categorical filter values), so the
    Rules agent can locate the rows/columns and compute the value without guessing.
    """
    source_file: str | None = None
    sheet: str | None = None
    header_row_index: int | None = None
    columns: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    dedup_key: str | None = None
    aggregation: str | None = None
    expected_value: str | None = None
    notes: str | None = None


class EvidenceHint(BaseModel):
    """One concise Stage 1 investigative hint per independently verifiable claim."""
    text: str = Field(min_length=1, max_length=1200)
    observed: list[HintFact] = Field(default_factory=list)
    inferred: list[HintFact] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    verification_plan: VerificationPlan | None = None
    version: int = 1
