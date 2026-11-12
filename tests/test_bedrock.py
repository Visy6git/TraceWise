from __future__ import annotations

from app.services import bedrock


def test_build_bedrock_model_uses_session_region(monkeypatch):
    monkeypatch.setattr(bedrock, "BEDROCK_ENABLED", True)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    model = bedrock.build_bedrock_model(
        model_id="us.anthropic.claude-sonnet-5-5",
        region="us-east-1",
    )

    assert model is not None
    assert model.client.meta.region_name == "us-east-1"
    assert model.config["model_id"] == "us.anthropic.claude-sonnet-5-5"
