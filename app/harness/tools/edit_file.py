"""Scoped edit_file tool strictly confined to the harness workspace cwd."""
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


class EditParams(BaseModel):
    path: str = Field(..., description="Relative file path inside workspace")
    old_string: str = Field("", description="Exact text to replace (empty only when creating a new file)")
    new_string: str = Field(..., description="Replacement text")
    replace_all: bool = Field(False, description="Replace all occurrences when true")


class EditTool(Tool):
    name = "edit_file"
    description = (
        "Edit an existing file in the workspace by exact text replacement. "
        "Ensure old_string matches exact indentation and whitespace."
    )
    kind = ToolKind.WRITE
    schema = EditParams

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        params = EditParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)
        outside_cwd = not is_within_dir(path, invocation.cwd)
        in_readonly = is_within_any_dir(path, self.config.resolved_readonly_dirs())
        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=f"Edit file: {path.name}",
            affected_paths=[path],
            is_dangerous=outside_cwd or in_readonly,
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = EditParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)

        if not is_within_dir(path, invocation.cwd):
            return ToolResult.error_result(f"Edit denied outside workspace: {params.path}")
        if is_within_any_dir(path, self.config.resolved_readonly_dirs()):
            return ToolResult.error_result(f"Edit denied in read-only directory: {params.path}")

        ext_path = to_extended_path(path)
        if not ext_path.exists():
            if params.old_string:
                return ToolResult.error_result(
                    f"File does not exist: {params.path}. Use write_file or leave old_string empty."
                )
            ensure_parent_directory(path)
            ext_path.write_text(params.new_string, encoding="utf-8")
            return ToolResult.success_result(
                f"Created {params.path}",
                diff=FileDiff(path=path, old_content="", new_content=params.new_string, is_new_file=True),
                metadata={"path": str(path), "is_new_file": True},
            )

        old_content = ext_path.read_text(encoding="utf-8")
        if not params.old_string:
            return ToolResult.error_result(
                "old_string is empty on an existing file; provide exact text to replace or use write_file."
            )

        count = old_content.count(params.old_string)
        if count == 0:
            return ToolResult.error_result(f"old_string not found in {params.path}")
        if count > 1 and not params.replace_all:
            return ToolResult.error_result(
                f"old_string found {count} times in {params.path}; provide more context or set replace_all=true."
            )

        new_content = (
            old_content.replace(params.old_string, params.new_string)
            if params.replace_all
            else old_content.replace(params.old_string, params.new_string, 1)
        )
        if new_content == old_content:
            return ToolResult.error_result("No changes applied (old_string equals new_string)")

        ext_path.write_text(new_content, encoding="utf-8")
        return ToolResult.success_result(
            f"Edited {params.path}: replaced {count if params.replace_all else 1} occurrence(s)",
            diff=FileDiff(path=path, old_content=old_content, new_content=new_content),
            metadata={"path": str(path)},
        )

