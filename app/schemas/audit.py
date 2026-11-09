"""Append-only audit/event metadata schemas."""
from pydantic import BaseModel, Field
from typing import Any


class AuditRecord(BaseModel):
    audit_id: str
    run_id: str
    actor_type: str = Field(pattern="^(human|agent|tool|system)$")
    actor_id: str
    action: str
    object_type: str
    object_id: str
    object_version: int | None = None
    before_hash: str | None = None
    after_hash: str | None = None
    correlation_id: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str
