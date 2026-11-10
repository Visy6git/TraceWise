"""Scoped write_file tool strictly confined to the harness workspace cwd."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.harness.paths import (
    ensure_parent_directory,
    is_within_any_dir,
    is_within_dir,
    resolve_path,
    to_extended_path,
)
from app.harness.tools.base import FileDiff, Tool, ToolConfirmation, ToolInvocation, ToolKind, ToolResult


class WriteFileParams(BaseModel):
    path: str = Field(..., description="Relative file path inside the workspace")
    content: str = Field(..., description="Full file content to write")
    create_directories: bool = Field(True, description="Create parent directories if needed")


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Write content to a file inside the current workspace directory (creates or replaces the file). "
        "Parent directories are created automatically."
    )
    kind = ToolKind.WRITE
    schema = WriteFileParams

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        params = WriteFileParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)
        outside_cwd = not is_within_dir(path, invocation.cwd)
        in_readonly = is_within_any_dir(path, self.config.resolved_readonly_dirs())
        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=f"Write file: {path.name}",
            affected_paths=[path],
            is_dangerous=outside_cwd or in_readonly,
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WriteFileParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)

        if not is_within_dir(path, invocation.cwd):
            return ToolResult.error_result(f"Write denied outside workspace: {params.path}")
        if is_within_any_dir(path, self.config.resolved_readonly_dirs()):
            return ToolResult.error_result(f"Write denied in read-only directory: {params.path}")

        ext_path = to_extended_path(path)
        is_new = not ext_path.exists()
        old_content = ""
        if not is_new:
            try:
                old_content = ext_path.read_text(encoding="utf-8")
            except OSError:
                pass

        try:
            if params.create_directories:
                ensure_parent_directory(path)
            elif not path.parent.exists():
                return ToolResult.error_result(f"Parent directory does not exist: {path.parent}")

            ext_path.write_text(params.content, encoding="utf-8")
            action = "Created" if is_new else "Updated"
            line_count = len(params.content.splitlines())
            return ToolResult.success_result(
                f"{action} {params.path} ({line_count} lines)",
                diff=FileDiff(path=path, old_content=old_content, new_content=params.content, is_new_file=is_new),
                metadata={
                    "path": str(path),
                    "is_new_file": is_new,
                    "lines": line_count,
                    "bytes": len(params.content.encode("utf-8")),
                },
            )
        except OSError as exc:
            return ToolResult.error_result(f"Failed to write file: {exc}")

