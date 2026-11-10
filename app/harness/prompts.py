"""Clean system prompts for the TraceWise agentic harness."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.harness.config import HarnessConfig
    from app.harness.tools.base import Tool


def get_system_prompt(
    config: HarnessConfig,
    tools: list[Tool] | None = None,
) -> str:
    cwd_str = str(config.resolved_cwd())
    ro_strs = [str(p) for p in config.resolved_readonly_dirs()]
    ro_section = (
        "\nRead-only data directories (DO NOT modify or delete files here):\n- "
        + "\n- ".join(ro_strs)
        if ro_strs
        else ""
    )

    tool_names = ", ".join(t.name for t in (tools or [])) or "read_file, write_file, edit_file, list_dir, grep, glob, shell"

    parts = [
        "# TraceWise Autonomous Data & Code Harness\n",
        f"Current writable workspace directory: `{cwd_str}`{ro_section}",
        f"Available tools: {tool_names}",
        (
            "\n## Operational Rules\n"
            "1. Read original source files strictly from `SOURCE_INPUT_DIR` (or listed read-only directories). NEVER modify, rename, or write inside `SOURCE_INPUT_DIR`.\n"
            "2. Write all generated Python scripts, Markdown reports, tests, and JSON outputs ONLY inside the current workspace directory (`cwd`).\n"
            "3. Never fabricate file paths, sheet names, column names, counts, or test results. Inspect the real data and verify every script by executing it with `shell`.\n"
            "4. When running Python scripts via `shell`, check stdout/stderr completely. If an error occurs, read the traceback, inspect columns/values, edit the script, and re-run.\n"
            "5. Keep your final assistant response concise and strictly factual based only on observed tool outputs."
        ),
    ]

    if config.developer_instructions:
        parts.append(f"\n## Task Instructions\n{config.developer_instructions}")

    if config.user_instructions:
        parts.append(f"\n## Additional Context\n{config.user_instructions}")

    return "\n".join(parts)


def get_compression_prompt() -> str:
    return (
        "Summarize the technical work completed so far concisely: "
        "files written, scripts executed, exact observations (sheet names, columns, unique values, "
        "computed values, errors fixed), and remaining steps."
    )

