"""Base tool interfaces for the TraceWise coding-agent harness."""
from __future__ import annotations

import abc
import difflib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic.json_schema import model_json_schema

from app.harness.config import HarnessConfig


class ToolKind(str, Enum):
    READ = "read"
    WRITE = "write"
    SHELL = "shell"


@dataclass
class FileDiff:
    path: Path
    old_content: str
    new_content: str
    is_new_file: bool = False
    is_deletion: bool = False

    def to_diff(self) -> str:
        old_lines = self.old_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)
        if old_lines and not old_lines[-1].endswith("\n"):
            old_lines[-1] += "\n"
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        old_name = "/dev/null" if self.is_new_file else str(self.path)
        new_name = "/dev/null" if self.is_deletion else str(self.path)
        return "".join(difflib.unified_diff(old_lines, new_lines, fromfile=old_name, tofile=new_name))


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    diff: FileDiff | None = None
    exit_code: int | None = None

    @classmethod
    def error_result(cls, error: str, output: str = "", **kwargs: Any) -> ToolResult:
        return cls(success=False, output=output, error=error, **kwargs)

    @classmethod
    def success_result(cls, output: str, **kwargs: Any) -> ToolResult:
        return cls(success=True, output=output, error=None, **kwargs)

    def to_model_output(self) -> str:
        if self.success:
            return self.output or "(ok)"
        return f"Error: {self.error}\n\nOutput:\n{self.output}".strip()


@dataclass
class ToolInvocation:
    params: dict[str, Any]
    cwd: Path


@dataclass
class ToolConfirmation:
    tool_name: str
    params: dict[str, Any]
    description: str
    diff: FileDiff | None = None
    affected_paths: list[Path] = field(default_factory=list)
    command: str | None = None
    is_dangerous: bool = False


class Tool(abc.ABC):
    name: str = "base_tool"
    description: str = "Base tool"
    kind: ToolKind = ToolKind.READ

    def __init__(self, config: HarnessConfig) -> None:
        self.config = config

    @property
    def schema(self) -> dict[str, Any] | type[BaseModel]:
        raise NotImplementedError("Tool must define schema")

    @abc.abstractmethod
    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        pass

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        schema = self.schema
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                schema(**params)
            except ValidationError as exc:
                errors: list[str] = []
                for err in exc.errors():
                    loc = ".".join(str(x) for x in err.get("loc", []))
                    errors.append(f"Parameter '{loc}': {err.get('msg', 'Invalid')}")
                return errors
            except Exception as exc:
                return [str(exc)]
        return []

    def is_mutating(self, params: dict[str, Any]) -> bool:
        return self.kind in {ToolKind.WRITE, ToolKind.SHELL}

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        if not self.is_mutating(invocation.params):
            return None
        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=f"Execute {self.name}",
        )

    def to_openai_schema(self) -> dict[str, Any]:
        schema = self.schema
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            json_schema = model_json_schema(schema, mode="serialization")
            return {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": json_schema.get("properties", {}),
                    "required": json_schema.get("required", []),
                },
            }
        if isinstance(schema, dict):
            params = schema["parameters"] if "parameters" in schema else schema
            return {"name": self.name, "description": self.description, "parameters": params}
        raise ValueError(f"Invalid schema for tool {self.name}")

