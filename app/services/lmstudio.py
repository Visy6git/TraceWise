"""LM Studio / OpenAI-compatible adapter with native Strands Agent tool-calling support."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, AsyncGenerator

import httpx
from strands.models.model import Model
from strands.types.streaming import StreamEvent

from app.config import (
    LLM_PROVIDER,
    LMSTUDIO_BASE_URL,
    LMSTUDIO_ENABLED,
    LMSTUDIO_MAX_TOKENS,
    LMSTUDIO_MODEL_ID,
    LMSTUDIO_TIMEOUT,
    is_live_llm_enabled,
)

logger = logging.getLogger(__name__)


def normalize_base_url(url: str | None = None) -> str:
    raw = (url or LMSTUDIO_BASE_URL).strip().rstrip("/")
    if not raw.endswith("/v1"):
        return f"{raw}/v1"
    return raw


def check_lmstudio_health(base_url: str | None = None, timeout: float = 3.0) -> dict[str, Any]:
    url = f"{normalize_base_url(base_url)}/models"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
            return {"status": "ok", "url": url, "models": models}
    except Exception as exc:
        return {"status": "error", "url": url, "error": str(exc)}


def _clean_thinking_tags(text: str) -> str:
    if "<think>" in text and "</think>" in text:
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if cleaned:
            return cleaned
    return text.strip()


def _render_tool_result_content(content_list: Any) -> str:
    if not isinstance(content_list, list):
        return str(content_list)
    parts: list[str] = []
    for item in content_list:
        if not isinstance(item, dict):
            parts.append(str(item))
        elif "text" in item:
            parts.append(str(item["text"]))
        elif "json" in item:
            parts.append(json.dumps(item["json"], ensure_ascii=False))
        else:
            parts.append(json.dumps(item, ensure_ascii=False))
    return "\n".join(parts)


def convert_strands_messages_to_openai(
    messages: Any,
    system_prompt: str | list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Translate Strands `Messages` (including toolUse & toolResult blocks) into OpenAI messages."""
    openai_msgs: list[dict[str, Any]] = []

    if system_prompt:
        if isinstance(system_prompt, list):
            sys_text = "\n".join(str(b.get("text", "")) for b in system_prompt if isinstance(b, dict))
        else:
            sys_text = str(system_prompt)
        if sys_text.strip():
            openai_msgs.append({"role": "system", "content": sys_text})

    if not isinstance(messages, list):
        openai_msgs.append({"role": "user", "content": str(messages)})
        return openai_msgs

    for m in messages:
        if not isinstance(m, dict):
            openai_msgs.append({"role": "user", "content": str(m)})
            continue

        role = m.get("role", "user")
        blocks = m.get("content", [])
        if isinstance(blocks, str):
            openai_msgs.append({"role": role, "content": blocks})
            continue
        if not isinstance(blocks, list):
            openai_msgs.append({"role": role, "content": str(blocks)})
            continue

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if "text" in block and block["text"] is not None:
                    text_parts.append(str(block["text"]))
                elif "toolUse" in block:
                    tu = block["toolUse"]
                    tu_input = tu.get("input", {})
                    args_str = (
                        tu_input
                        if isinstance(tu_input, str)
                        else json.dumps(tu_input, ensure_ascii=False)
                    )
                    tool_calls.append(
                        {
                            "id": tu.get("toolUseId", f"call_{len(tool_calls)}"),
                            "type": "function",
                            "function": {
                                "name": tu.get("name", ""),
                                "arguments": args_str,
                            },
                        }
                    )
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(text_parts) if text_parts else None,
            }
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            if assistant_msg["content"] is None and not tool_calls:
                assistant_msg["content"] = ""
            openai_msgs.append(assistant_msg)
        else:
            user_texts: list[str] = []
            for block in blocks:
                if not isinstance(block, dict):
                    user_texts.append(str(block))
                    continue
                if "toolResult" in block:
                    tr = block["toolResult"]
                    openai_msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": tr.get("toolUseId", "call_0"),
                            "content": _render_tool_result_content(tr.get("content", [])),
                        }
                    )
                elif "text" in block and block["text"] is not None:
                    user_texts.append(str(block["text"]))
            if user_texts:
                openai_msgs.append({"role": "user", "content": "\n".join(user_texts)})

    return openai_msgs


def convert_strands_tool_specs(tool_specs: list[Any] | None) -> list[dict[str, Any]]:
    if not tool_specs:
        return []
    tools: list[dict[str, Any]] = []
    for spec in tool_specs:
        if not isinstance(spec, dict):
            continue
        input_schema = spec.get("inputSchema") or {}
        params = (
            input_schema.get("json", input_schema)
            if isinstance(input_schema, dict)
            else {"type": "object", "properties": {}}
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": spec.get("name", ""),
                    "description": spec.get("description", ""),
                    "parameters": params,
                },
            }
        )
    return tools


def invoke_lmstudio(
    prompt: str,
    model_id: str | None = None,
    base_url: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.1,
    timeout: float | None = None,
    system_prompt: str | None = None,
) -> str:
    """Synchronous helper invoking OpenAI-compatible LM Studio /chat/completions."""
    if not (LMSTUDIO_ENABLED or LLM_PROVIDER in {"lmstudio", "openai"} or is_live_llm_enabled()):
        raise RuntimeError(
            "LM Studio is not enabled in configuration (set LMSTUDIO_ENABLED=true or LLM_PROVIDER=lmstudio)"
        )

    selected_model = model_id or LMSTUDIO_MODEL_ID
    target_base = normalize_base_url(base_url)
    endpoint = f"{target_base}/chat/completions"
    call_timeout = timeout or LMSTUDIO_TIMEOUT
    limit_tokens = max_tokens or LMSTUDIO_MAX_TOKENS

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": selected_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": limit_tokens,
    }

    try:
        with httpx.Client(timeout=call_timeout) as client:
            response = client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Could not connect to LM Studio at {target_base}. Ensure local server is running."
        ) from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"LM Studio timed out after {call_timeout}s for model {selected_model}."
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"LM Studio HTTP {exc.response.status_code}: {exc.response.text}") from exc

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(f"LM Studio returned no choices: {data}")
    message = choices[0].get("message", {})
    raw_content = message.get("content") or choices[0].get("text") or ""
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise RuntimeError("LM Studio returned an empty response")
    return _clean_thinking_tags(raw_content)


class LMStudioStrandsModel(Model):
    """Strands Model with full native tool calling (`tools` + `toolUse` + `toolResult`)."""

    def __init__(
        self,
        model_id: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.model_id = model_id or LMSTUDIO_MODEL_ID
        self.base_url = normalize_base_url(base_url)
        self.temperature = temperature
        self.max_tokens = max_tokens or LMSTUDIO_MAX_TOKENS
        self.timeout = timeout or LMSTUDIO_TIMEOUT
        self.transport = transport

    def get_config(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }

    def update_config(self, **model_config: Any) -> None:
        if "model_id" in model_config:
            self.model_id = model_config["model_id"]
        if "base_url" in model_config:
            self.base_url = normalize_base_url(model_config["base_url"])
        if "temperature" in model_config:
            self.temperature = float(model_config["temperature"])
        if "max_tokens" in model_config:
            self.max_tokens = int(model_config["max_tokens"])
        if "timeout" in model_config:
            self.timeout = float(model_config["timeout"])

    async def structured_output(
        self,
        output_model: type[Any],
        prompt: Any,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        raw = invoke_lmstudio(
            prompt=str(prompt),
            model_id=self.model_id,
            base_url=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            system_prompt=system_prompt,
        )
        try:
            from app.services.bedrock import parse_bedrock_json
            parsed = parse_bedrock_json(raw)
            validated = (
                output_model.model_validate(parsed)
                if hasattr(output_model, "model_validate")
                else output_model(**parsed)
            )
            yield {"output": validated}
        except Exception:
            yield {"raw_text": raw}

    async def stream(
        self,
        messages: Any,
        tool_specs: list[Any] | None = None,
        system_prompt: Any = None,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None]:
        start_ms = time.monotonic()
        openai_messages = convert_strands_messages_to_openai(messages, system_prompt)
        openai_tools = convert_strands_tool_specs(tool_specs)

        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": openai_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if openai_tools:
            payload["tools"] = openai_tools
            if isinstance(tool_choice, dict):
                if "any" in tool_choice:
                    payload["tool_choice"] = "required"
                elif "tool" in tool_choice and isinstance(tool_choice["tool"], dict):
                    payload["tool_choice"] = {
                        "type": "function",
                        "function": {"name": tool_choice["tool"].get("name", "")},
                    }
                else:
                    payload["tool_choice"] = "auto"
            else:
                payload["tool_choice"] = "auto"

        endpoint = f"{self.base_url}/chat/completions"
        client_kwargs: dict[str, Any] = {"timeout": httpx.Timeout(self.timeout)}
        if self.transport is not None:
            client_kwargs["transport"] = self.transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.post(endpoint, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Could not connect to LM Studio at {self.base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"LM Studio timed out after {self.timeout}s for model {self.model_id}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"LM Studio HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"LM Studio returned no choices: {data}")

        choice = choices[0]
        message = choice.get("message") or {}
        tool_calls = message.get("tool_calls") or []
        raw_content = message.get("content") or ""
        cleaned_content = _clean_thinking_tags(str(raw_content)) if raw_content else ""

        yield {"messageStart": {"role": "assistant"}}  # type: ignore[misc]

        block_idx = 0
        if cleaned_content:
            yield {"contentBlockStart": {"contentBlockIndex": block_idx, "start": {}}}  # type: ignore[misc]
            yield {"contentBlockDelta": {"contentBlockIndex": block_idx, "delta": {"text": cleaned_content}}}  # type: ignore[misc]
            yield {"contentBlockStop": {"contentBlockIndex": block_idx}}  # type: ignore[misc]
            block_idx += 1

        for idx, tc in enumerate(tool_calls):
            fn = tc.get("function") or {}
            call_id = tc.get("id") or f"call_{idx}"
            name = str(fn.get("name") or "")
            raw_args = fn.get("arguments")
            if isinstance(raw_args, dict):
                args_str = json.dumps(raw_args, ensure_ascii=False)
            elif isinstance(raw_args, str):
                args_str = raw_args
            else:
                args_str = "{}"

            yield {  # type: ignore[misc]
                "contentBlockStart": {
                    "contentBlockIndex": block_idx,
                    "start": {"toolUse": {"toolUseId": call_id, "name": name}},
                }
            }
            yield {  # type: ignore[misc]
                "contentBlockDelta": {
                    "contentBlockIndex": block_idx,
                    "delta": {"toolUse": {"input": args_str}},
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": block_idx}}  # type: ignore[misc]
            block_idx += 1

        if not cleaned_content and not tool_calls:
            yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}  # type: ignore[misc]
            yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": ""}}}  # type: ignore[misc]
            yield {"contentBlockStop": {"contentBlockIndex": 0}}  # type: ignore[misc]

        finish = str(choice.get("finish_reason") or "").lower()
        if tool_calls or finish == "tool_calls":
            stop_reason = "tool_use"
        elif finish == "length":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"

        yield {"messageStop": {"stopReason": stop_reason}}  # type: ignore[misc]

        usage = data.get("usage") or {}
        elapsed_ms = int((time.monotonic() - start_ms) * 1000)
        yield {  # type: ignore[misc]
            "metadata": {
                "usage": {
                    "inputTokens": int(usage.get("prompt_tokens", 0) or 0),
                    "outputTokens": int(usage.get("completion_tokens", 0) or 0),
                    "totalTokens": int(usage.get("total_tokens", 0) or 0),
                },
                "metrics": {"latencyMs": elapsed_ms},
            }
        }


def build_lmstudio_strands_model(
    model_id: str | None = None,
    base_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LMStudioStrandsModel | None:
    if not (LMSTUDIO_ENABLED or LLM_PROVIDER in {"lmstudio", "openai"} or is_live_llm_enabled()):
        return None
    return LMStudioStrandsModel(model_id=model_id, base_url=base_url, transport=transport)
