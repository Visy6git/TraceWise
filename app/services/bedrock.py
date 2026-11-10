"""AWS Bedrock configuration adapter using boto3 and Strands BedrockModel."""
from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.config import Config
from strands.models import BedrockModel

from app.config import (
    AWS_REGION,
    BEDROCK_ENABLED,
    BEDROCK_MODEL_ID,
    get_active_llm_provider,
)


def get_boto3_bedrock_client(region: str | None = None) -> Any:
    """Create a boto3 bedrock-runtime client with retry configuration."""
    region_name = region or AWS_REGION
    config = Config(
        region_name=region_name,
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=10,
        read_timeout=120,
    )
    session = boto3.Session()
    return session.client("bedrock-runtime", config=config)


def invoke_bedrock_native(
    prompt: str,
    model_id: str | None = None,
    region: str | None = None,
    max_tokens: int = 8192,
) -> str:
    """Invoke the configured AWS Bedrock model natively via boto3."""
    if not BEDROCK_ENABLED:
        raise RuntimeError("BEDROCK_ENABLED must be true to run live agent stages with Bedrock")

    selected_model_id = model_id or BEDROCK_MODEL_ID
    client = get_boto3_bedrock_client(region)
    response = client.converse(
        modelId=selected_model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens},
    )
    content = response.get("output", {}).get("message", {}).get("content", [])
    text = "\n".join(part["text"] for part in content if isinstance(part.get("text"), str))
    if not text.strip():
        raise RuntimeError("Bedrock returned an empty response")
    return text


def invoke_bedrock(
    prompt: str,
    model_id: str | None = None,
    region: str | None = None,
    max_tokens: int = 8192,
) -> str:
    """Invoke the active LLM backend. Routes to LM Studio when LM Studio is selected."""
    active_provider = get_active_llm_provider()
    if active_provider == "lmstudio":
        from app.services.lmstudio import invoke_lmstudio
        return invoke_lmstudio(
            prompt=prompt,
            model_id=model_id,
            max_tokens=max_tokens,
        )
    return invoke_bedrock_native(
        prompt=prompt,
        model_id=model_id,
        region=region,
        max_tokens=max_tokens,
    )


def build_bedrock_model(model_id: str | None = None, region: str | None = None) -> Any:
    """Build the Strands model adapter without masking configuration errors."""
    if not BEDROCK_ENABLED:
        return None
    selected_region = region or AWS_REGION
    return BedrockModel(
        model_id=model_id or BEDROCK_MODEL_ID,
        boto_session=boto3.Session(region_name=selected_region),
        boto_client_config=Config(
            region_name=selected_region,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
        region_name=selected_region,
    )


def parse_bedrock_json(response_text: str) -> Any:
    """Parse one JSON object or array from a model response, including fenced JSON."""
    candidate = response_text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1]
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[:-3].strip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(candidate):
        if character in "[{":
            try:
                value, _ = decoder.raw_decode(candidate[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError("LLM response did not contain valid JSON")
