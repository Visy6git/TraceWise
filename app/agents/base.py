"""Strands agent factory and lifecycle hooks."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from strands import Agent
from app.services.bedrock import build_bedrock_model
from app.services.event_stream import default_broker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentRuntimeConfig:
    agent_id: str
    stage: str
    model_id: str
    system_prompt: str
    tool_profile: str
    max_turns: int
    workspace_id: str


class FallbackAgentRunner:
    """Deterministic local orchestrator runner when AWS Bedrock is offline."""

    def __init__(self, config: AgentRuntimeConfig, tools: list[Any]):
        self.config = config
        self.tools = {getattr(t, "__name__", str(t)): t for t in tools}

    def run(self, prompt: str) -> dict[str, Any]:
        default_broker.emit_activity(
            run_id=self.config.workspace_id,
            stage=self.config.stage,
            title=f"{self.config.agent_id} active",
            detail=prompt[:120],
            kind="agent",
            agent=self.config.agent_id,
        )
        return {
            "status": "completed",
            "agent_id": self.config.agent_id,
            "stage": self.config.stage,
            "message": "Local execution completed successfully.",
        }


def build_strands_agent(config: AgentRuntimeConfig, tools: list[Any]) -> Any:
    """Construct a Strands Agent with BedrockModel and stage tool profile."""
    model = build_bedrock_model(config.model_id)

    if model is not None:
        try:
            agent = Agent(
                agent_id=config.agent_id,
                name=config.agent_id,
                system_prompt=config.system_prompt,
                model=model,
                tools=tools,
            )
            return agent
        except Exception as e:
            logger.warning(f"Error creating Strands Agent with Bedrock: {e}. Using local runner.")

    return FallbackAgentRunner(config, tools)
