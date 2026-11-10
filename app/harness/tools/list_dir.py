"""Scoped list_dir tool for the TraceWise harness."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.harness.paths import is_within_any_dir, resolve_path
from app.harness.tools.base import Tool, ToolInvocation, ToolKind, ToolResult


class ListDirParams(BaseModel):
    path: str = Field(".", description="Directory path to list (default: workspace root)")
    include_hidden: bool = Field(False, description="Include dotfiles when true")


class ListDirTool(Tool):
    name = "list_dir"
    description = "List contents of a workspace or read-only source directory."
    kind = ToolKind.READ
    schema = ListDirParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ListDirParams(**invocation.params)
        dir_path = resolve_path(invocation.cwd, params.path)

        allowed_roots = [invocation.cwd, *self.config.resolved_readonly_dirs()]
        if not is_within_any_dir(dir_path, allowed_roots):
            return ToolResult.error_result(f"Access denied outside workspace/source roots: {params.path}")

        if not dir_path.exists() or not dir_path.is_dir():
            return ToolResult.error_result(f"Directory does not exist: {params.path}")

        try:
            items = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as exc:
            return ToolResult.error_result(f"Error listing directory: {exc}")

        if not params.include_hidden:
            items = [item for item in items if not item.name.startswith(".")]

        if not items:
            return ToolResult.success_result("Directory is empty.", metadata={"entries": 0})

        lines = [f"{item.name}/" if item.is_dir() else item.name for item in items]
        return ToolResult.success_result(
            "\n".join(lines),
            metadata={"path": str(dir_path), "entries": len(items)},
        )

