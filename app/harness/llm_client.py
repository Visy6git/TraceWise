"""Async LLM client for the harness supporting LM Studio / OpenAI (httpx) and AWS Bedrock."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncGenerator, Callable

import boto3
from botocore.config import Config as BotoConfig
import httpx

from app.harness.config import HarnessConfig
from app.harness.events import (
    StreamEvent,
    StreamEventType,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolCallDelta,
    parse_tool_call_arguments,
)


def _strip_think_tags(text: str) -> str:
    if "<think>" in text and "</think>" in text:
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if cleaned:
            return cleaned
    return text


class LLMClient:
    """Async chat+tool client built directly on httpx (no `openai` package needed) and boto3."""

    def __init__(
        self,
        config: HarnessConfig,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._transport = transport
        self._client_factory = client_factory
        self._max_retries = 3

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                kwargs: dict[str, Any] = {
                    "timeout": httpx.Timeout(self.config.timeout),
                    "headers": {
                        "Authorization": f"Bearer {self.config.effective_api_key()}",
                        "Content-Type": "application/json",
                    },
                }
                if self._transport is not None:
                    kwargs["transport"] = self._transport
                self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _build_openai_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> AsyncGenerator[StreamEvent, None]:
        provider = self.config.effective_provider()
        if provider == "bedrock":
            async for ev in self._bedrock_converse(messages, tools):
                yield ev
            return

        endpoint = f"{self.config.effective_base_url()}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.effective_model_name(),
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.model.max_tokens,
            "stream": stream,
        }
        if tools:
            payload["tools"] = self._build_openai_tools(tools)
            payload["tool_choice"] = "auto"

        for attempt in range(self._max_retries + 1):
            try:
                client = self._get_http_client()
                if stream:
                    async for ev in self._openai_stream(client, endpoint, payload):
                        yield ev
                else:
                    async for ev in self._openai_non_stream(client, endpoint, payload):
                        yield ev
                return
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, 4))
                    continue
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    error=f"LLM request failed after retries: {exc}",
                )
                return
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                body_text = exc.response.text
                if status_code in {429, 502, 503, 504} and attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, 4))
                    continue
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    error=f"LLM HTTP {status_code}: {body_text[:400]}",
                )
                return
            except Exception as exc:
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    error=f"LLM client error: {exc}",
                )
                return

    async def _openai_non_stream(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        payload: dict[str, Any],
    ) -> AsyncGenerator[StreamEvent, None]:
        resp = await client.post(endpoint, json=payload)
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise ValueError(f"Empty choices in LLM response: {data}")

        choice = choices[0]
        msg = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")

        raw_content = msg.get("content") or ""
        cleaned_content = _strip_think_tags(raw_content) if isinstance(raw_content, str) else ""
        if cleaned_content:
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(content=cleaned_content),
            )

        raw_tool_calls = msg.get("tool_calls") or []
        for idx, tc in enumerate(raw_tool_calls):
            fn = tc.get("function") or {}
            call_id = tc.get("id") or f"call_{idx}"
            name = fn.get("name")
            args_raw = fn.get("arguments") or "{}"
            args_dict = (
                args_raw if isinstance(args_raw, dict) else parse_tool_call_arguments(str(args_raw))
            )
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_START,
                tool_call_delta=ToolCallDelta(call_id=call_id, name=name),
            )
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(call_id=call_id, name=name, arguments=args_dict),
            )

        usage_raw = data.get("usage") or {}
        usage = TokenUsage(
            input_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
            total_tokens=int(usage_raw.get("total_tokens", 0) or 0),
        )

        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            finish_reason=finish_reason,
            usage=usage,
        )

    async def _openai_stream(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        payload: dict[str, Any],
    ) -> AsyncGenerator[StreamEvent, None]:
        async with client.stream("POST", endpoint, json=payload) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            # Defensive fallback if mock or server responds with plain JSON despite stream=True
            if "application/json" in content_type and "text/event-stream" not in content_type:
                body = await resp.aread()
                data = json.loads(body.decode("utf-8"))
                async for ev in self._yield_from_openai_json(data):
                    yield ev
                return

            finish_reason: str | None = None
            usage: TokenUsage | None = None
            tool_acc: dict[int, dict[str, Any]] = {}

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                chunk_str = line[5:].strip()
                if chunk_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(chunk_str)
                except json.JSONDecodeError:
                    continue

                if chunk.get("usage"):
                    u = chunk["usage"]
                    usage = TokenUsage(
                        input_tokens=int(u.get("prompt_tokens", 0) or 0),
                        output_tokens=int(u.get("completion_tokens", 0) or 0),
                        total_tokens=int(u.get("total_tokens", 0) or 0),
                    )

                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

                delta = choice.get("delta") or {}
                if delta.get("content"):
                    yield StreamEvent(
                        type=StreamEventType.TEXT_DELTA,
                        text_delta=TextDelta(content=str(delta["content"])),
                    )

                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index", 0))
                    if idx not in tool_acc:
                        tool_acc[idx] = {
                            "id": tc.get("id") or f"call_{idx}",
                            "name": None,
                            "arguments": "",
                        }
                    if tc.get("id"):
                        tool_acc[idx]["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        tool_acc[idx]["name"] = fn["name"]
                        yield StreamEvent(
                            type=StreamEventType.TOOL_CALL_START,
                            tool_call_delta=ToolCallDelta(
                                call_id=tool_acc[idx]["id"], name=fn["name"]
                            ),
                        )
                    if fn.get("arguments"):
                        tool_acc[idx]["arguments"] += str(fn["arguments"])

            for idx in sorted(tool_acc.keys()):
                tc = tool_acc[idx]
                yield StreamEvent(
                    type=StreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=ToolCall(
                        call_id=tc["id"],
                        name=tc["name"],
                        arguments=parse_tool_call_arguments(tc["arguments"]),
                    ),
                )

            yield StreamEvent(
                type=StreamEventType.MESSAGE_COMPLETE,
                finish_reason=finish_reason,
                usage=usage,
            )

    async def _yield_from_openai_json(self, data: dict[str, Any]) -> AsyncGenerator[StreamEvent, None]:
        choices = data.get("choices") or []
        if not choices:
            yield StreamEvent(type=StreamEventType.MESSAGE_COMPLETE)
            return
        choice = choices[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        if content:
            yield StreamEvent(
                type=StreamEventType.TEXT_DELTA,
                text_delta=TextDelta(content=_strip_think_tags(str(content))),
            )
        for idx, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            call_id = tc.get("id") or f"call_{idx}"
            name = fn.get("name")
            args_raw = fn.get("arguments") or "{}"
            args_dict = (
                args_raw if isinstance(args_raw, dict) else parse_tool_call_arguments(str(args_raw))
            )
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_START,
                tool_call_delta=ToolCallDelta(call_id=call_id, name=name),
            )
            yield StreamEvent(
                type=StreamEventType.TOOL_CALL_COMPLETE,
                tool_call=ToolCall(call_id=call_id, name=name, arguments=args_dict),
            )
        usage_raw = data.get("usage") or {}
        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            finish_reason=choice.get("finish_reason"),
            usage=TokenUsage(
                input_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
                total_tokens=int(usage_raw.get("total_tokens", 0) or 0),
            ),
        )

    async def _bedrock_converse(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        system_blocks: list[dict[str, Any]] = []
        converse_msgs: list[dict[str, Any]] = []

        for m in messages:
            role = m.get("role")
            if role == "system":
                if m.get("content"):
                    system_blocks.append({"text": str(m["content"])})
            elif role == "assistant":
                blocks: list[dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"text": str(m["content"])})
                for tc in m.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    args_str = fn.get("arguments", "{}")
                    args_obj = parse_tool_call_arguments(args_str) if isinstance(args_str, str) else args_str
                    blocks.append(
                        {
                            "toolUse": {
                                "toolUseId": tc.get("id", "call_0"),
                                "name": fn.get("name", ""),
                                "input": args_obj,
                            }
                        }
                    )
                if blocks:
                    converse_msgs.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                converse_msgs.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "toolResult": {
                                    "toolUseId": m.get("tool_call_id", "call_0"),
                                    "content": [{"text": str(m.get("content", ""))}],
                                }
                            }
                        ],
                    }
                )
            else:
                converse_msgs.append(
                    {"role": "user", "content": [{"text": str(m.get("content", ""))}]}
                )

        kwargs: dict[str, Any] = {
            "modelId": self.config.effective_model_name(),
            "messages": converse_msgs,
            "inferenceConfig": {
                "maxTokens": self.config.model.max_tokens,
                "temperature": self.config.temperature,
            },
        }
        if system_blocks:
            kwargs["system"] = system_blocks
        if tools:
            kwargs["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "inputSchema": {"json": t.get("parameters", {"type": "object", "properties": {}})},
                        }
                    }
                    for t in tools
                ]
            }

        def _call() -> dict[str, Any]:
            client = boto3.Session(region_name=self.config.aws_region).client(
                "bedrock-runtime",
                config=BotoConfig(
                    region_name=self.config.aws_region,
                    retries={"max_attempts": 3, "mode": "standard"},
                    read_timeout=int(self.config.timeout),
                ),
            )
            return client.converse(**kwargs)

        try:
            resp = await asyncio.to_thread(_call)
        except Exception as exc:
            yield StreamEvent(type=StreamEventType.ERROR, error=f"Bedrock converse error: {exc}")
            return

        out_msg = resp.get("output", {}).get("message", {})
        for block in out_msg.get("content", []):
            if "text" in block and block["text"]:
                yield StreamEvent(
                    type=StreamEventType.TEXT_DELTA,
                    text_delta=TextDelta(content=block["text"]),
                )
            elif "toolUse" in block:
                tu = block["toolUse"]
                call_id = tu.get("toolUseId", "call_0")
                name = tu.get("name", "")
                args = tu.get("input", {}) or {}
                yield StreamEvent(
                    type=StreamEventType.TOOL_CALL_START,
                    tool_call_delta=ToolCallDelta(call_id=call_id, name=name),
                )
                yield StreamEvent(
                    type=StreamEventType.TOOL_CALL_COMPLETE,
                    tool_call=ToolCall(call_id=call_id, name=name, arguments=args),
                )

        usage_raw = resp.get("usage") or {}
        yield StreamEvent(
            type=StreamEventType.MESSAGE_COMPLETE,
            finish_reason=resp.get("stopReason"),
            usage=TokenUsage(
                input_tokens=int(usage_raw.get("inputTokens", 0) or 0),
                output_tokens=int(usage_raw.get("outputTokens", 0) or 0),
                total_tokens=int(usage_raw.get("totalTokens", 0) or 0),
            ),
        )

