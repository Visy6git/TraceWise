"""Scoped glob tool for matching files in workspace or read-only directories."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.harness.paths import display_path_rel_to_cwd, is_within_any_dir, resolve_path
from app.harness.tools.base import Tool, ToolInvocation, ToolKind, ToolResult


class GlobParams(BaseModel):
    pattern: str = Field(..., description="Glob pattern to match (supports **)")
    path: str = Field(".", description="Directory to search in")


class GlobTool(Tool):
    name = "glob"
    description = "Find files matching a glob pattern inside workspace or read-only directories."
    kind = ToolKind.READ
    schema = GlobParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = GlobParams(**invocation.params)
        search_path = resolve_path(invocation.cwd, params.path)

        allowed_roots = [invocation.cwd, *self.config.resolved_readonly_dirs()]
        if not is_within_any_dir(search_path, allowed_roots):
            return ToolResult.error_result(f"Access denied outside workspace/source roots: {params.path}")
        if not search_path.exists() or not search_path.is_dir():
            return ToolResult.error_result(f"Directory does not exist: {params.path}")

        try:
            matches = [p for p in search_path.glob(params.pattern) if p.is_file()]
        except Exception as exc:
            return ToolResult.error_result(f"Glob error: {exc}")

        lines = [display_path_rel_to_cwd(p, invocation.cwd) for p in matches[:500]]
        if len(matches) > 500:
            lines.append("... (limited to 500 matches)")

        return ToolResult.success_result(
            "\n".join(lines) if lines else "No matching files.",
            metadata={"matches": len(matches)},
        )

