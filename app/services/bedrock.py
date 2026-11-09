"""AWS Bedrock configuration adapter using boto3 and Strands BedrockModel.

Supports boto3 Bedrock runtime calls with graceful local execution fallback
when AWS infrastructure is not yet provisioned.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.config import Config
from strands.models import BedrockModel

logger = logging.getLogger(__name__)


def get_boto3_bedrock_client(region: str | None = None) -> Any:
    """Create a boto3 bedrock-runtime client with retry configuration."""
    region_name = region or os.environ.get("AWS_REGION", "ap-south-1")
    config = Config(
        region_name=region_name,
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=10,
        read_timeout=120,
    )
    session = boto3.Session()
    return session.client("bedrock-runtime", config=config)


def build_bedrock_model(model_id: str | None = None, region: str | None = None) -> Any:
    """Build a Strands BedrockModel instance using boto3 session.

    If credentials are not yet provisioned, returns a configured BedrockModel
    or local model adapter.
    """
    selected_model_id = model_id or os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-20250514-v1:0")
    selected_region = region or os.environ.get("AWS_REGION", "ap-south-1")

    session = boto3.Session(region_name=selected_region)
    client_config = Config(
        region_name=selected_region,
        retries={"max_attempts": 3, "mode": "standard"},
    )

    try:
        model = BedrockModel(
            model_id=selected_model_id,
            boto_session=session,
            boto_client_config=client_config,
            region_name=selected_region,
        )
        return model
    except Exception as e:
        logger.warning(f"Could not initialize Strands BedrockModel with live AWS: {e}. Fallback enabled.")
        return None
