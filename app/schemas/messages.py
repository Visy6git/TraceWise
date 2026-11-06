from __future__ import annotations
import time
from typing import Any
from pydantic import BaseModel, Field


class AgentMessage(BaseModel):
    message_id: str
    sender: str
    recipient: str
    intent: str
    claim_id: str | None = None
    section_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

