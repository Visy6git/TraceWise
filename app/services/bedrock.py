"""AWS Bedrock adapter for Anthropic Claude Sonnet.
Provides tool use, multi-turn tool interaction loop, chat converse,
and structured agent prompt orchestration via boto3.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any, Callable
import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Default to a supported US inference profile rather than an on-demand foundation model ID.
DEFAULT_SONNET_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5-5")


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
    """Single-turn converse helper for Claude Sonnet via AWS Bedrock Converse API."""
    model_id = os.getenv("BEDROCK_MODEL_ID", DEFAULT_SONNET_MODEL_ID)
    try:
        client = get_bedrock_client()
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        inference_config: dict[str, Any] = {"maxTokens": max_tokens}
        if "sonnet-5" not in model_id.lower():
            inference_config["temperature"] = temperature
        kwargs: dict[str, Any] = {
            "modelId": model_id,
            "system": [{"text": system}],
            "messages": messages,
            "inferenceConfig": inference_config,
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


def converse_with_tools(
    initial_prompt: str,
    tools: list[dict[str, Any]],
    tool_executor: Callable[[str, dict[str, Any]], Any],
    *,
    system: str = "You are an autonomous pharmacovigilance data investigation agent. Use tools to inspect schemas, explore data, and formulate deterministic rules.",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    max_turns: int = 10,
    on_tool_call: Callable[[str, dict[str, Any], Any], None] | None = None,
) -> dict[str, Any]:
    """Multi-turn autonomous tool interaction loop with Bedrock Converse API.

    1. Sends user prompt + tool specs
    2. Receives Sonnet toolUse
    3. Executes tool in Python
    4. Sends toolResult back to Bedrock
    5. Repeats until end_turn or max_turns
    """
    model_id = os.getenv("BEDROCK_MODEL_ID", DEFAULT_SONNET_MODEL_ID)
    client = get_bedrock_client()

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": initial_prompt}]}
    ]
    tool_history: list[dict[str, Any]] = []

    inference_config: dict[str, Any] = {"maxTokens": max_tokens}
    if "sonnet-5" not in model_id.lower():
        inference_config["temperature"] = temperature

    kwargs: dict[str, Any] = {
        "modelId": model_id,
        "system": [{"text": system}],
        "inferenceConfig": inference_config,
        "toolConfig": {
            "tools": [{"toolSpec": t} for t in tools],
            "toolChoice": {"auto": {}},
        },
    }

    turn = 0
    while turn < max_turns:
        turn += 1
        kwargs["messages"] = messages

        try:
            response = client.converse(**kwargs)
        except Exception as exc:
            return {
                "success": False,
                "error": f"Bedrock Converse error at turn {turn}: {str(exc)}",
                "tool_history": tool_history,
                "messages": messages,
                "text": "",
            }

        output_msg = response.get("output", {}).get("message", {})
        stop_reason = response.get("stopReason")
        content_blocks = output_msg.get("content", [])
        messages.append(output_msg)

        tool_uses = [b.get("toolUse") for b in content_blocks if "toolUse" in b and b.get("toolUse")]

        if not tool_uses or stop_reason == "end_turn":
            # Completed reasoning
            final_text = "".join(b.get("text", "") for b in content_blocks if "text" in b)
            return {
                "success": True,
                "text": final_text,
                "tool_history": tool_history,
                "turns": turn,
                "stop_reason": stop_reason,
                "model_id": model_id,
            }

        # Handle tool uses
        tool_results_content: list[dict[str, Any]] = []
        for tu in tool_uses:
            tool_id = tu.get("toolUseId")
            tool_name = tu.get("name")
            tool_input = tu.get("input", {})

            try:
                result_data = tool_executor(tool_name, tool_input)
                status = "success"
            except Exception as tool_err:
                result_data = {"error": str(tool_err), "is_error": True}
                status = "error"

            tool_history.append({
                "turn": turn,
                "tool_id": tool_id,
                "tool_name": tool_name,
                "input": tool_input,
                "result": result_data,
                "status": status,
            })

            if on_tool_call:
                try:
                    on_tool_call(tool_name, tool_input, result_data)
                except Exception:
                    pass

            tool_results_content.append({
                "toolResult": {
                    "toolUseId": tool_id,
                    "content": [{"text": json.dumps(result_data, default=str)}],
                    "status": status,
                }
            })

        messages.append({
            "role": "user",
            "content": tool_results_content,
        })

    # If exceeded max turns, extract whatever text is present
    last_text = "".join(
        b.get("text", "")
        for msg in reversed(messages)
        if msg.get("role") == "assistant"
        for b in msg.get("content", [])
        if "text" in b
    )
    return {
        "success": True,
        "text": last_text,
        "tool_history": tool_history,
        "turns": turn,
        "stop_reason": "max_turns_reached",
        "model_id": model_id,
    }
