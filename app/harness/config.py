"""Configuration models for the TraceWise coding-agent harness."""
from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config import (
    AWS_REGION,
    BEDROCK_MODEL_ID,
    BEDROCK_SEND_TEMPERATURE,
    LMSTUDIO_BASE_URL,
    LMSTUDIO_MODEL_ID,
    LMSTUDIO_TIMEOUT,
    get_active_llm_provider,
)
from app.harness.paths import strip_extended_prefix


class ModelConfig(BaseModel):
    name: str = Field(
        default_factory=lambda: (
            BEDROCK_MODEL_ID if get_active_llm_provider() == "bedrock" else LMSTUDIO_MODEL_ID
        )
    )
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    context_window: int = Field(default=32768, ge=1024)
    max_tokens: int = Field(default=4096, ge=256)


class ShellEnvironmentPolicy(BaseModel):
    ignore_default_excludes: bool = False
    exclude_patterns: list[str] = Field(
        default_factory=lambda: ["*KEY*", "*TOKEN*", "*SECRET*", "*PASSWORD*", "*CREDENTIAL*"]
    )
    set_vars: dict[str, str] = Field(default_factory=dict)


class ApprovalPolicy(str, Enum):
    ON_REQUEST = "on-request"
    ON_FAILURE = "on-failure"
    AUTO = "auto"
    AUTO_EDIT = "auto-edit"
    NEVER = "never"
    YOLO = "yolo"


class HarnessConfig(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    cwd: Path = Field(default_factory=Path.cwd)
    readonly_dirs: list[Path] = Field(default_factory=list)
    provider: str = Field(default_factory=get_active_llm_provider)
    api_key: str | None = Field(default=None)
    base_url: str | None = Field(default=None)
    aws_region: str = Field(default_factory=lambda: AWS_REGION)
    bedrock_send_temperature: bool = Field(default_factory=lambda: BEDROCK_SEND_TEMPERATURE)
    timeout: float = Field(default_factory=lambda: LMSTUDIO_TIMEOUT, ge=5.0)
    shell_environment: ShellEnvironmentPolicy = Field(default_factory=ShellEnvironmentPolicy)
    max_turns: int = Field(default=30, ge=1)
    max_tool_output_tokens: int = Field(default=12000, ge=500)
    approval: ApprovalPolicy = ApprovalPolicy.AUTO
    allowed_tools: list[str] | None = None
    developer_instructions: str | None = None
    user_instructions: str | None = None

    @property
    def model_name(self) -> str:
        return self.model.name

    @model_name.setter
    def model_name(self, value: str) -> None:
        self.model.name = value

    @property
    def temperature(self) -> float:
        return self.model.temperature

    @temperature.setter
    def temperature(self, value: float) -> None:
        self.model.temperature = value

    def resolved_cwd(self) -> Path:
        return strip_extended_prefix(self.cwd).resolve()

    def resolved_readonly_dirs(self) -> list[Path]:
        return [strip_extended_prefix(p).resolve() for p in self.readonly_dirs]

    def effective_provider(self) -> str:
        p = (self.provider or get_active_llm_provider()).strip().lower()
        return p if p in {"lmstudio", "bedrock", "openai", "mock"} else "lmstudio"

    def effective_base_url(self) -> str:
        raw = self.base_url or os.environ.get("BASE_URL") or LMSTUDIO_BASE_URL
        raw = raw.strip().rstrip("/")
        if not raw.endswith("/v1"):
            return f"{raw}/v1"
        return raw

    def effective_api_key(self) -> str:
        return self.api_key or os.environ.get("API_KEY") or os.environ.get("OPENAI_API_KEY") or "lm-studio"

    def effective_model_name(self) -> str:
        if self.effective_provider() == "bedrock":
            if self.model.name == LMSTUDIO_MODEL_ID:
                return BEDROCK_MODEL_ID
            return self.model.name or BEDROCK_MODEL_ID
        return self.model.name or LMSTUDIO_MODEL_ID

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
