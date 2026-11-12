"""Throwaway: minimal live Bedrock converse through the harness client.

Confirms the `temperature`-deprecation fix lets the harness LLM client talk to the
configured Bedrock model (us.anthropic.claude-sonnet-5-5).
"""
from __future__ import annotations

import asyncio

from app.config import AWS_REGION, BEDROCK_MODEL_ID, BEDROCK_SEND_TEMPERATURE
from app.harness.config import HarnessConfig
from app.harness.events import StreamEventType
from app.harness.llm_client import LLMClient


async def main() -> None:
    print(f"model={BEDROCK_MODEL_ID} region={AWS_REGION} send_temperature={BEDROCK_SEND_TEMPERATURE}")
    cfg = HarnessConfig(provider="bedrock")
    cfg.model.max_tokens = 64
    client = LLMClient(cfg)
    texts: list[str] = []
    error: str | None = None
    async for ev in client.chat_completion(
        [{"role": "user", "content": "Reply with exactly: PONG"}],
        tools=None,
        stream=False,
    ):
        if ev.type == StreamEventType.TEXT_DELTA and ev.text_delta:
            texts.append(ev.text_delta.content)
        elif ev.type == StreamEventType.ERROR:
            error = ev.error
    await client.close()
    if error:
        print("LIVE_RESULT=ERROR", error)
    else:
        print("LIVE_RESULT=OK", "".join(texts).strip()[:120])


if __name__ == "__main__":
    asyncio.run(main())
