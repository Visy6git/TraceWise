"""Scoped read_file tool for the TraceWise harness (fixes truncate_text call and enforces path scope)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.harness.paths import (
    is_binary_file,
    is_within_any_dir,
    resolve_path,
    to_extended_path,
)
from app.harness.text import count_tokens, truncate_text
from app.harness.tools.base import Tool, ToolInvocation, ToolKind, ToolResult


class ReadFileParams(BaseModel):
    path: str = Field(..., description="Relative path inside workspace or readable path in SOURCE_INPUT_DIR")
    offset: int = Field(1, ge=1, description="1-based start line number")
    limit: int | None = Field(None, ge=1, description="Maximum number of lines to read")


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read the contents of a text file with line numbers. Use offset and limit for partial reads. "
        "Does not read binary Excel workbooks directly—use a Python script via shell for .xlsx files."
    )
    kind = ToolKind.READ
    schema = ReadFileParams

    MAX_FILE_SIZE = 10 * 1024 * 1024
    MAX_OUTPUT_TOKENS = 16000

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ReadFileParams(**invocation.params)
        path = resolve_path(invocation.cwd, params.path)

        allowed_roots = [invocation.cwd, *self.config.resolved_readonly_dirs()]
        if not is_within_any_dir(path, allowed_roots):
            return ToolResult.error_result(
                f"Access denied: {params.path} is outside workspace and read-only input directories"
            )

        ext_path = to_extended_path(path)
        if not ext_path.exists():
            return ToolResult.error_result(f"File not found: {params.path}")
        if not ext_path.is_file():
            return ToolResult.error_result(f"Path is not a file: {params.path}")

        file_size = ext_path.stat().st_size
        if file_size > self.MAX_FILE_SIZE:
            return ToolResult.error_result(f"File too large ({file_size / (1024 * 1024):.1f} MB)")

        if is_binary_file(ext_path):
            return ToolResult.error_result(
                f"Cannot read binary file '{path.name}' as text. Use Python via shell (openpyxl/pandas) for Excel files."
            )

        try:
            try:
                content = ext_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = ext_path.read_text(encoding="latin-1")

            lines = content.splitlines()
            total_lines = len(lines)
            if total_lines == 0:
                return ToolResult.success_result("File is empty.", metadata={"lines": 0})

            start_idx = max(0, params.offset - 1)
            end_idx = min(start_idx + params.limit, total_lines) if params.limit is not None else total_lines

            formatted = [f"{i:6}|{line}" for i, line in enumerate(lines[start_idx:end_idx], start=start_idx + 1)]
            output = "\n".join(formatted)

            truncated = False
            model_name = self.config.effective_model_name()
            if count_tokens(output, model_name) > self.MAX_OUTPUT_TOKENS:
                output = truncate_text(
                    output,
                    model_name,
                    self.MAX_OUTPUT_TOKENS,
                    suffix=f"\n... [truncated {total_lines} total lines]",
                )
                truncated = True

            if start_idx > 0 or end_idx < total_lines:
                output = f"Showing lines {start_idx + 1}-{end_idx} of {total_lines}\n\n" + output

            return ToolResult.success_result(
                output=output,
                truncated=truncated,
                metadata={
                    "path": str(path),
                    "total_lines": total_lines,
                    "shown_start": start_idx + 1,
                    "shown_end": end_idx,
                },
            )
        except Exception as exc:
            return ToolResult.error_result(f"Failed to read file: {exc}")

