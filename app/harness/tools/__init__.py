"""Built-in workspace and shell tools for the TraceWise harness."""
from app.harness.tools.base import FileDiff, Tool, ToolConfirmation, ToolInvocation, ToolKind, ToolResult
from app.harness.tools.edit_file import EditTool
from app.harness.tools.glob import GlobTool
from app.harness.tools.grep import GrepTool
from app.harness.tools.list_dir import ListDirTool
from app.harness.tools.read_file import ReadFileTool
from app.harness.tools.shell import ShellTool
from app.harness.tools.write_file import WriteFileTool


def get_all_builtin_tools() -> list[type[Tool]]:
    return [
        ReadFileTool,
        WriteFileTool,
        EditTool,
        ShellTool,
        ListDirTool,
        GrepTool,
        GlobTool,
    ]


__all__ = [
    "EditTool",
    "FileDiff",
    "GlobTool",
    "GrepTool",
    "ListDirTool",
    "ReadFileTool",
    "ShellTool",
    "Tool",
    "ToolConfirmation",
    "ToolInvocation",
    "ToolKind",
    "ToolResult",
    "WriteFileTool",
    "get_all_builtin_tools",
]

