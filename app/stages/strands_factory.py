"""Unified Strands Agent builder for LM Studio (OpenAI tools) and AWS Bedrock."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from strands import Agent

from app.config import MOCK_RUNS_ENABLED, get_active_llm_provider
from app.services.bedrock import build_bedrock_model
from app.services.lmstudio import build_lmstudio_strands_model

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentRuntimeConfig:
    agent_id: str
    stage: str
    model_id: str | None
    system_prompt: str
    max_turns: int
    run_id: str


def build_strands_agent(config: AgentRuntimeConfig, tools: list[Any]) -> Agent | None:
    """Build a live Strands Agent with native tool calling for LM Studio or Bedrock."""
    provider = get_active_llm_provider()
    if MOCK_RUNS_ENABLED or provider == "mock":
        return None

    if provider in {"lmstudio", "openai"}:
        model = build_lmstudio_strands_model(config.model_id)
    else:
        model = build_bedrock_model(config.model_id)

    if model is None:
        raise RuntimeError(
            "Live LLM provider is required when MOCK_RUNS_ENABLED is false "
            "(configure LMSTUDIO_ENABLED=true or BEDROCK_ENABLED=true)"
        )

    return Agent(
        agent_id=config.agent_id,
        name=config.agent_id,
        system_prompt=config.system_prompt,
        model=model,
        tools=tools,
    )

