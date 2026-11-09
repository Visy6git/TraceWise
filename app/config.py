"""Runtime configuration shared by the API and agent stages."""
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
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))

if MAX_UPLOAD_MB < 1:
    raise ValueError("MAX_UPLOAD_MB must be a positive integer")
