"""Typed routing boundary. This is a local router contract, not remote A2A transport."""
from __future__ import annotations

from typing import Any
from app.schemas.messages import MessageEnvelope
from app.control_plane.message_acl import AgentIdentity, authorize_message


class TaskRouter:
    def __init__(self, persistence: Any = None):
        self.persistence = persistence
        self.inbox: dict[str, list[MessageEnvelope]] = {}

    def route(self, message: MessageEnvelope, sender: AgentIdentity, recipient: AgentIdentity) -> str:
        authorize_message(sender, recipient, via_control_plane=True, artifact_refs=message.artifact_refs)
        
        recipient_key = f"{recipient.stage}:{recipient.agent_id}"
        if recipient_key not in self.inbox:
            self.inbox[recipient_key] = []
        self.inbox[recipient_key].append(message)
        
        return message.message_id
