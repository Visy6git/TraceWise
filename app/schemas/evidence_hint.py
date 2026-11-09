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


class EvidenceHint(BaseModel):
    """One concise Stage 1 investigative hint per independently verifiable claim."""
    text: str = Field(min_length=1, max_length=1200)
    observed: list[HintFact] = Field(default_factory=list)
    inferred: list[HintFact] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    version: int = 1
