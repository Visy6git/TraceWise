"""Scoped grep tool for searching text files inside workspace or read-only dirs."""
from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.harness.paths import (
    display_path_rel_to_cwd,
    is_binary_file,
    is_within_any_dir,
    resolve_path,
)
from app.harness.tools.base import Tool, ToolInvocation, ToolKind, ToolResult


class GrepParams(BaseModel):
    pattern: str = Field(..., description="Regular expression pattern to search for")
    path: str = Field(".", description="File or directory to search in")
    case_insensitive: bool = Field(False, description="Case-insensitive search")


class GrepTool(Tool):
    name = "grep"
    description = "Search for a regex pattern in text files inside the workspace or read-only directories."
    kind = ToolKind.READ
    schema = GrepParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = GrepParams(**invocation.params)
        search_path = resolve_path(invocation.cwd, params.path)

        allowed_roots = [invocation.cwd, *self.config.resolved_readonly_dirs()]
        if not is_within_any_dir(search_path, allowed_roots):
            return ToolResult.error_result(f"Access denied outside workspace/source roots: {params.path}")
        if not search_path.exists():
            return ToolResult.error_result(f"Path does not exist: {params.path}")

        try:
            regex = re.compile(params.pattern, re.IGNORECASE if params.case_insensitive else 0)
        except re.error as exc:
            return ToolResult.error_result(f"Invalid regex pattern: {exc}")

        files = self._find_files(search_path) if search_path.is_dir() else [search_path]
        output_lines: list[str] = []
        matches = 0

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception:
                continue

            file_header_added = False
            for idx, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    matches += 1
                    if not file_header_added:
                        rel = display_path_rel_to_cwd(file_path, invocation.cwd)
                        output_lines.append(f"=== {rel} ===")
                        file_header_added = True
                    output_lines.append(f"{idx}: {line}")
                    if matches >= 200:
                        break
            if file_header_added:
                output_lines.append("")
            if matches >= 200:
                output_lines.append("... [match limit reached]")
                break

        if not output_lines:
            return ToolResult.success_result(
                f"No matches found for '{params.pattern}'",
                metadata={"matches": 0, "files_searched": len(files)},
            )

        return ToolResult.success_result(
            "\n".join(output_lines),
            metadata={"matches": matches, "files_searched": len(files)},
        )

    def _find_files(self, search_path: Path) -> list[Path]:
        files: list[Path] = []
        for root, dirs, filenames in os.walk(search_path):
            dirs[:] = [
                d for d in dirs if d not in {"node_modules", "__pycache__", ".git", ".venv", "venv"}
            ]
            for name in filenames:
                if name.startswith("."):
                    continue
                p = Path(root) / name
                if not is_binary_file(p):
                    files.append(p)
                    if len(files) >= 500:
                        return files
        return files

