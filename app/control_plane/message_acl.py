"""Stage isolation and artifact-only communication policy."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    stage: str
    role: str


class MessageDenied(PermissionError):
    pass


def authorize_message(sender: AgentIdentity, recipient: AgentIdentity, *, via_control_plane: bool, artifact_refs: list[str]) -> None:
    """Disallow direct Claims<->Rules communication, even if both are local processes."""
    if sender.agent_id == recipient.agent_id:
        raise MessageDenied("Self-routing is not an agent communication operation")
    if sender.stage != recipient.stage:
        if not via_control_plane or not artifact_refs:
            raise MessageDenied("Cross-stage exchange is only allowed through versioned artifacts routed by the Run Control Plane")
        allowed = {("claims", "rules"), ("rules", "evaluation"), ("claims", "evaluation")}
        if (sender.stage, recipient.stage) not in allowed:
            raise MessageDenied("Unsupported cross-stage direction")
    elif not via_control_plane:
        raise MessageDenied("All messages must be mediated by the control plane")
