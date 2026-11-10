"""Lightweight hook callback system for the TraceWise harness."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


ToolCallback = Callable[[str, dict[str, Any], Any | None], Awaitable[None] | None]


@dataclass
class HookSystem:
    on_before_tool: list[ToolCallback] = field(default_factory=list)
    on_after_tool: list[ToolCallback] = field(default_factory=list)

    async def trigger_before_tool(self, tool_name: str, tool_params: dict[str, Any]) -> None:
        for cb in self.on_before_tool:
            res = cb(tool_name, tool_params, None)
            if res is not None:
                await res

    async def trigger_after_tool(self, tool_name: str, tool_params: dict[str, Any], tool_result: Any) -> None:
        for cb in self.on_after_tool:
            res = cb(tool_name, tool_params, tool_result)
            if res is not None:
                await res

