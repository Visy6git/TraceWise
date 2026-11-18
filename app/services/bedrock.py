from __future__ import annotations
import json
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from app.config import settings


class BedrockNotConfigured(RuntimeError):
    pass


def invoke_json(system_prompt: str, user_prompt: str) -> dict:
    if not settings.bedrock_enabled:
        raise BedrockNotConfigured("Bedrock is disabled. Enable BEDROCK_ENABLED and configure BEDROCK_MODEL_ID to use the optional LLM agents.")
    if not settings.bedrock_model_id:
        raise BedrockNotConfigured("BEDROCK_MODEL_ID is empty. Set the model ID or inference-profile ARN enabled for your account/region.")
    client=boto3.client("bedrock-runtime",region_name=settings.aws_region)
    try:
        response=client.converse(
            modelId=settings.bedrock_model_id,
            system=[{"text":system_prompt}],
            messages=[{"role":"user","content":[{"text":user_prompt}]}],
            inferenceConfig={"maxTokens":settings.bedrock_max_tokens,"temperature":settings.bedrock_temperature},
        )
        output="".join(x.get("text","") for x in response["output"]["message"]["content"] if "text" in x).strip()
        if output.startswith("```"):
            output=output.split("\n",1)[-1].rsplit("```",1)[0].strip()
        start,end=output.find("{"),output.rfind("}")
        if start<0 or end<=start: raise ValueError("Bedrock model did not return a JSON object")
        return json.loads(output[start:end+1])
    except (BotoCoreError,ClientError) as exc:
        raise RuntimeError(f"Bedrock Converse failed: {exc}") from exc
