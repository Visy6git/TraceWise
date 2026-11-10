"""Tool registry dispatching harness tools with hooks and safety checks."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.harness.approval import ApprovalContext, ApprovalDecision, ApprovalManager
from app.harness.config import HarnessConfig
from app.harness.hooks import HookSystem
from app.harness.tools import get_all_builtin_tools
from app.harness.tools.base import Tool, ToolInvocation, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, config: HarnessConfig) -> None:
        self.config = config
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_tools(self) -> list[Tool]:
        tools = list(self._tools.values())
        if self.config.allowed_tools:
            allowed = set(self.config.allowed_tools)
            tools = [t for t in tools if t.name in allowed]
        return tools

    def get_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_openai_schema() for tool in self.get_tools()]

    async def invoke(
        self,
        name: str,
        params: dict[str, Any],
        cwd: Path,
        hook_system: HookSystem,
        approval_manager: ApprovalManager | None = None,
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            result = ToolResult.error_result(f"Unknown tool: {name}", metadata={"tool_name": name})
            await hook_system.trigger_after_tool(name, params, result)
            return result

        validation_errors = tool.validate_params(params)
        if validation_errors:
            result = ToolResult.error_result(
                f"Invalid parameters: {'; '.join(validation_errors)}",
                metadata={"tool_name": name, "validation_errors": validation_errors},
            )
            await hook_system.trigger_after_tool(name, params, result)
            return result

        await hook_system.trigger_before_tool(name, params)
        invocation = ToolInvocation(params=params, cwd=cwd)

        if approval_manager:
            confirmation = await tool.get_confirmation(invocation)
            if confirmation:
                ctx = ApprovalContext(
                    tool_name=name,
                    params=params,
                    is_mutating=tool.is_mutating(params),
                    affected_paths=confirmation.affected_paths,
                    command=confirmation.command,
                    is_dangerous=confirmation.is_dangerous,
                )
                decision = await approval_manager.check_approval(ctx)
                if decision == ApprovalDecision.REJECTED:
                    result = ToolResult.error_result("Operation rejected by workspace safety policy")
                    await hook_system.trigger_after_tool(name, params, result)
                    return result
                if decision == ApprovalDecision.NEEDS_CONFIRMATION:
                    if not approval_manager.request_confirmation(confirmation):
                        result = ToolResult.error_result("Operation requires approval and was declined")
                        await hook_system.trigger_after_tool(name, params, result)
                        return result

        try:
            result = await tool.execute(invocation)
        except Exception as exc:
            logger.exception("Harness tool %s failed unexpectedly", name)
            result = ToolResult.error_result(f"Internal tool error: {exc}", metadata={"tool_name": name})

        await hook_system.trigger_after_tool(name, params, result)
        return result


def create_default_registry(config: HarnessConfig) -> ToolRegistry:
    registry = ToolRegistry(config)
    for tool_cls in get_all_builtin_tools():
        registry.register(tool_cls(config))
    return registry

