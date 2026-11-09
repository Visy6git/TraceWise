from enum import StrEnum
from pydantic import BaseModel, Field
from typing import Any


class StageName(StrEnum):
    claims = "claims"
    rules = "rules"
    evaluation = "evaluation"


class MessageEnvelope(BaseModel):
    """Typed message envelope routed by the Run Control Plane, never peer-to-peer."""
    message_id: str
    run_id: str
    stage: StageName
    sender_agent_id: str
    recipient_agent_id: str
    message_type: str
    artifact_refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str
    created_at: str
    expires_at: str | None = None
