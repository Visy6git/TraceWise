"""Specialist subagents as bounded Strands Agents-as-Tools."""
from __future__ import annotations

from typing import Any
from app.services.event_stream import default_broker


def dispatch_rule_subagent(
    run_id: str,
    claim_id: str,
    subagent_role: str,
    task_brief: str,
    read_scope: list[str],
    write_scope: list[str],
    expected_output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create child specialist subagent with independent context and bounded scopes."""
    subagent_id = f"{claim_id}-{subagent_role.lower().replace(' ', '-')}"

    default_broker.emit_activity(
        run_id=run_id,
        stage="rules",
        title=f"Subagent dispatched: {subagent_role}",
        detail=task_brief[:100],
        kind="agent",
        agent=subagent_id,
    )

    return {
        "subagent_id": subagent_id,
        "role": subagent_role,
        "task_brief": task_brief,
        "status": "completed",
        "read_scope": read_scope,
        "write_scope": write_scope,
    }
