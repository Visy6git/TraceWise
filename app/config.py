"""Runtime configuration shared by the API, Strands stages, and coding harness."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def _read_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{name} must be 'true' or 'false'")
    return normalized == "true"


MOCK_RUNS_ENABLED = _read_bool("MOCK_RUNS_ENABLED", True)
BEDROCK_ENABLED = _read_bool("BEDROCK_ENABLED", False)
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-20250514-v1:0"
)
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

LMSTUDIO_ENABLED = _read_bool("LMSTUDIO_ENABLED", False)
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
LMSTUDIO_MODEL_ID = os.environ.get("LMSTUDIO_MODEL_ID", "google/gemma-4-e4b")
LMSTUDIO_TIMEOUT = float(os.environ.get("LMSTUDIO_TIMEOUT", "120.0"))
LMSTUDIO_MAX_TOKENS = int(os.environ.get("LMSTUDIO_MAX_TOKENS", "8192"))

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "").strip().lower()

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))
if MAX_UPLOAD_MB < 1:
    raise ValueError("MAX_UPLOAD_MB must be a positive integer")


def get_active_llm_provider() -> str:
    """Resolve the active LLM provider based on config flags."""
    if LLM_PROVIDER in {"lmstudio", "bedrock", "openai"}:
        return LLM_PROVIDER
    if LMSTUDIO_ENABLED:
        return "lmstudio"
    if BEDROCK_ENABLED:
        return "bedrock"
    if MOCK_RUNS_ENABLED:
        return "mock"
    return "lmstudio"


def is_live_llm_enabled() -> bool:
    """Return True when a live LLM backend (LM Studio, OpenAI, or Bedrock) is configured."""
    return (
        BEDROCK_ENABLED
        or LMSTUDIO_ENABLED
        or LLM_PROVIDER in {"lmstudio", "bedrock", "openai"}
    )
