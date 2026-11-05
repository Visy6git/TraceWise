"""AWS Bedrock adapter for Anthropic Claude 3.5 Sonnet.
Provides tool use, chat converse, and structured agent prompt orchestration via boto3.
"""
from typing import Any
import os
import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Default Sonnet model ID on AWS Bedrock (Claude 3.5 Sonnet v2)
DEFAULT_SONNET_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")


def get_bedrock_client():
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("bedrock-runtime", region_name=region)


def is_bedrock_available() -> tuple[bool, str]:
    """Checks if Bedrock is configured and credentials are functional."""
    enabled = os.getenv("BEDROCK_ENABLED", "false").lower() == "true"
    if not enabled:
        return False, "Bedrock is disabled (BEDROCK_ENABLED is not set to true)."
    try:
        session = boto3.Session()
        creds = session.get_credentials()
        if not creds:
            return False, "No AWS credentials detected in environment/credential chain."
        return True, f"Bedrock configured with model {DEFAULT_SONNET_MODEL_ID}"
    except Exception as exc:
        return False, f"AWS credential error: {str(exc)}"


def converse_sonnet(
    prompt: str,
    *,
    system: str = "You are a pharmacovigilance data intelligence agent. Analyze data deterministically and formulate exact lineage rules.",
    temperature: float = 0.1,
    max_tokens: int = 4096,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Invokes Claude 3.5 Sonnet via AWS Bedrock Converse API with optional tool specifications."""
    model_id = os.getenv("BEDROCK_MODEL_ID", DEFAULT_SONNET_MODEL_ID)
    try:
        client = get_bedrock_client()
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        kwargs: dict[str, Any] = {
            "modelId": model_id,
            "system": [{"text": system}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
        }

        if tools:
            kwargs["toolConfig"] = {
                "tools": [{"toolSpec": t} for t in tools],
                "toolChoice": {"auto": {}},
            }

        response = client.converse(**kwargs)
        output = response.get("output", {}).get("message", {})
        content_blocks = output.get("content", [])

        text_parts = [b.get("text", "") for b in content_blocks if "text" in b]
        tool_uses = [b.get("toolUse") for b in content_blocks if "toolUse" in b]

        return {
            "success": True,
            "text": "".join(text_parts),
            "tool_uses": tool_uses,
            "stop_reason": response.get("stopReason"),
            "usage": response.get("usage", {}),
            "model_id": model_id,
        }
    except (BotoCoreError, ClientError, Exception) as err:
        return {
            "success": False,
            "error": str(err),
            "model_id": model_id,
            "text": "",
            "tool_uses": [],
        }
