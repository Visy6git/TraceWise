"""Base Agent class providing event publication, telemetry, and LLM Converse loop."""
from __future__ import annotations
import json
import os
from typing import Any, Callable
from ..services.ag_ui import ag_ui_manager
from ..services.bedrock import is_bedrock_available, converse_sonnet, converse_with_tools


class BaseAgent:
    def __init__(self, run_id: str, agent_id: str, agent_name: str, agent_role: str):
        self.run_id = run_id
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.agent_role = agent_role

    def emit(self, event_type: str, summary: str, details: dict[str, Any] | None = None):
        """Emits an AG-UI event with agent identity."""
        ag_ui_manager.emit(
            run_id=self.run_id,
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            agent_role=self.agent_role,
            event_type=event_type,
            summary=summary,
            details=details or {},
        )

    def invoke_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        tool_executor: Callable[[str, dict[str, Any]], Any],
        system_prompt: str | None = None,
        max_turns: int = 10,
    ) -> dict[str, Any]:
        """Runs the Converse tool-execution loop with Bedrock or local fallback."""
        bedrock_enabled = os.getenv("BEDROCK_ENABLED", "false").lower() == "true"
        bedrock_ok, _ = is_bedrock_available()

        def on_tool(name: str, inp: dict[str, Any], res: Any):
            self.emit(
                "agent_tool_call",
                f"{self.agent_name} called tool '{name}'",
                {"tool": name, "input": inp, "summary": str(res)[:200]},
            )

        if bedrock_enabled and bedrock_ok:
            return converse_with_tools(
                initial_prompt=prompt,
                tools=tools,
                tool_executor=tool_executor,
                system=system_prompt or "You are an autonomous pharmacovigilance data intelligence agent.",
                max_turns=max_turns,
                on_tool_call=on_tool,
            )

        # Fallback local deterministic execution
        return self._local_fallback_execution(prompt, tools, tool_executor)

    def _local_fallback_execution(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        tool_executor: Callable[[str, dict[str, Any]], Any],
    ) -> dict[str, Any]:
        """Provides deterministic fallback when Bedrock is disabled or running offline."""
        return {
            "success": True,
            "text": "Local deterministic agent reasoning.",
            "tool_history": [],
            "turns": 1,
            "model_id": "local-deterministic-engine",
        }

