from __future__ import annotations
import json
import re
import threading
from typing import Any, TypeVar
import httpx
from pydantic import BaseModel, ValidationError
from app.config import settings

T = TypeVar("T", bound=BaseModel)
_LMSTUDIO_SEM_LOCK = threading.Lock()
_LMSTUDIO_SEMAPHORE: threading.Semaphore | None = None


def _lmstudio_slot() -> threading.Semaphore:
    global _LMSTUDIO_SEMAPHORE
    with _LMSTUDIO_SEM_LOCK:
        if _LMSTUDIO_SEMAPHORE is None:
            _LMSTUDIO_SEMAPHORE = threading.Semaphore(max(1, int(getattr(settings, "lmstudio_max_concurrency", 1))))
        return _LMSTUDIO_SEMAPHORE


class LLMNotConfigured(RuntimeError):
    pass


class LLMInvocationError(RuntimeError):
    pass


def normalize_lmstudio_base_url(url: str) -> str:
    clean = (url or "http://127.0.0.1:1234/v1").strip().rstrip("/")
    if not clean.endswith("/v1"):
        clean = f"{clean}/v1"
    return clean


def llm_status_info() -> dict[str, Any]:
    provider = (settings.llm_provider or "lmstudio").strip().lower()
    lm_ready = bool(settings.lmstudio_enabled and settings.lmstudio_base_url and settings.lmstudio_model_id)
    br_ready = bool(settings.bedrock_enabled and settings.bedrock_model_id)

    if provider == "lmstudio" and lm_ready:
        active_provider = "lmstudio"
        active_model = settings.lmstudio_model_id
        enabled = True
    elif provider == "bedrock" and br_ready:
        active_provider = "bedrock"
        active_model = settings.bedrock_model_id
        enabled = True
    elif lm_ready:
        active_provider = "lmstudio"
        active_model = settings.lmstudio_model_id
        enabled = True
    elif br_ready:
        active_provider = "bedrock"
        active_model = settings.bedrock_model_id
        enabled = True
    else:
        active_provider = "none"
        active_model = ""
        enabled = False

    return {
        "llm_enabled": enabled,
        "llm_provider": active_provider,
        "llm_model_id": active_model,
        "lmstudio_enabled": settings.lmstudio_enabled,
        "lmstudio_base_url": normalize_lmstudio_base_url(settings.lmstudio_base_url),
        "lmstudio_model_id": settings.lmstudio_model_id,
        "bedrock_enabled": settings.bedrock_enabled,
        "bedrock_model_configured": bool(settings.bedrock_model_id),
        "region": settings.aws_region,
    }


def _strip_reasoning_and_extract_json(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    # Remove <think>...</think> blocks emitted by reasoning models (e.g. Qwen/Bonsai/DeepSeek)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()
    if text.startswith("```"):
        parts = text.split("\n", 1)
        text = parts[1] if len(parts) > 1 else text[3:]
        if "```" in text:
            text = text.rsplit("```", 1)[0]
        text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise LLMInvocationError("LLM response did not contain a valid JSON object.")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMInvocationError(f"Failed to parse JSON from LLM output: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMInvocationError("Expected a top-level JSON object from LLM.")
    return parsed


def _make_lmstudio_compatible_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Ensure Pydantic JSON schema works smoothly with OpenAI/LM Studio strict structured outputs."""
    out = json.loads(json.dumps(schema))

    def _walk(node: Any):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node.setdefault("additionalProperties", False)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(out)
    return out


def _call_lmstudio_chat(
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    json_schema: dict[str, Any],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    base_url = normalize_lmstudio_base_url(settings.lmstudio_base_url)
    endpoint = f"{base_url}/chat/completions"
    model = settings.lmstudio_model_id.strip()
    if not model:
        raise LLMNotConfigured("LMSTUDIO_MODEL_ID is not configured.")

    temp = settings.llm_temperature if temperature is None else temperature
    mtok = settings.llm_max_tokens if max_tokens is None else max_tokens
    compat_schema = _make_lmstudio_compatible_schema(json_schema)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Try strict json_schema first (LM Studio structured outputs), fallback gracefully if model rejects response_format
    attempts = [
        {
            "model": model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": mtok,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": compat_schema,
                },
            },
        },
        {
            "model": model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": mtok,
            "response_format": {"type": "json_object"},
        },
        {
            "model": model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": mtok,
        },
    ]

    last_error: Exception | None = None
    timeout = httpx.Timeout(settings.lmstudio_timeout, connect=10.0)
    with httpx.Client(timeout=timeout) as client:
        for payload in attempts:
            try:
                resp = client.post(endpoint, json=payload)
                if resp.status_code == 400 and "response_format" in payload:
                    # Model/server rejected strict schema format; try next fallback payload
                    last_error = LLMInvocationError(f"LM Studio HTTP 400: {resp.text[:300]}")
                    continue
                resp.raise_for_status()
                body = resp.json()
                choices = body.get("choices") or []
                if not choices:
                    raise LLMInvocationError("LM Studio returned no choices.")
                message = choices[0].get("message") or {}
                # Local reasoning models (e.g. prism-ml/bonsai-27b) in LM Studio may emit
                # structured JSON in `reasoning_content` when `content` is empty.
                raw_content = (message.get("content") or "").strip()
                raw_reasoning = (message.get("reasoning_content") or "").strip()
                candidates = [c for c in (raw_content, raw_reasoning) if c]
                if not candidates:
                    raise LLMInvocationError("LM Studio returned an empty assistant message.")
                parse_err: Exception | None = None
                for text_candidate in candidates:
                    try:
                        return _strip_reasoning_and_extract_json(text_candidate)
                    except LLMInvocationError as exc:
                        parse_err = exc
                raise parse_err or LLMInvocationError("Could not parse JSON from LM Studio response.")
            except httpx.ConnectError as exc:
                raise LLMInvocationError(
                    f"Cannot connect to LM Studio at {base_url}. Ensure LM Studio Local Server is running with model '{model}'."
                ) from exc
            except httpx.TimeoutException as exc:
                raise LLMInvocationError(
                    f"LM Studio timed out after {settings.lmstudio_timeout}s waiting for '{model}'."
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise LLMInvocationError(
                    f"LM Studio returned HTTP {exc.response.status_code}: {exc.response.text[:300]}"
                ) from exc
            except LLMInvocationError as exc:
                last_error = exc
                if "response_format" not in payload:
                    raise

    raise last_error or LLMInvocationError("LM Studio call failed.")


def invoke_structured(
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    schema_name: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> T:
    """Invoke the active configured LLM and validate its structured response against a Pydantic model."""
    status = llm_status_info()
    if not status["llm_enabled"]:
        raise LLMNotConfigured(
            "No LLM provider is enabled. Configure LMSTUDIO_ENABLED=true (LM Studio) or BEDROCK_ENABLED=true in .env."
        )

    json_schema = response_model.model_json_schema()
    provider = status["llm_provider"]

    if provider == "lmstudio":
        raw_obj = _call_lmstudio_chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_name=schema_name,
            json_schema=json_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif provider == "bedrock":
        from app.services.bedrock import invoke_json

        schema_instruction = (
            "\n\nReturn ONLY a single JSON object strictly matching this JSON Schema:\n"
            + json.dumps(json_schema, ensure_ascii=False)
        )
        raw_obj = invoke_json(system_prompt + schema_instruction, user_prompt)
    else:
        raise LLMNotConfigured(f"Unsupported LLM provider: {provider}")

    try:
        return response_model.model_validate(raw_obj)
    except ValidationError as exc:
        raise LLMInvocationError(f"LLM structured response failed schema validation: {exc}") from exc


def _coerce_param_value(raw_val: str) -> Any:
    val = (raw_val or "").strip()
    if not val:
        return ""
    low = val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null" or low == "none":
        return None
    if (val.startswith("[") and val.endswith("]")) or (val.startswith("{") and val.endswith("}")):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            pass
    if re.fullmatch(r"-?\d+", val):
        try:
            return int(val)
        except ValueError:
            pass
    return val


def _parse_xml_tool_call(text: str, expected_tool_name: str | None = None) -> dict[str, Any] | None:
    """Parse XML-style tool calls emitted by local reasoning models (e.g. Qwen/Bonsai in LM Studio):
    <tool_call><function=name><parameter=k>v</parameter>...</function></tool_call>
    """
    if not text or "<parameter=" not in text:
        return None
    blocks = re.findall(r"<function=([^>\s]+)\s*>(.*?)</function>", text, flags=re.S | re.I)
    if not blocks:
        # Fallback if closing </function> tag was truncated
        m = re.search(r"<function=([^>\s]+)\s*>(.*)$", text, flags=re.S | re.I)
        if m:
            blocks = [(m.group(1), m.group(2))]
    if not blocks:
        return None

    chosen_body = blocks[0][1]
    if expected_tool_name:
        for fn_name, fn_body in blocks:
            if fn_name.strip().lower() == expected_tool_name.strip().lower():
                chosen_body = fn_body
                break

    params = re.findall(r"<parameter=([^>\s]+)\s*>(.*?)</parameter>", chosen_body, flags=re.S | re.I)
    if not params:
        return None
    args: dict[str, Any] = {}
    for key, val in params:
        args[key.strip()] = _coerce_param_value(val)
    return args


def _extract_tool_arguments(message: dict[str, Any], expected_tool_name: str) -> dict[str, Any]:
    """Extract structured tool arguments from OpenAI tool_calls, XML tool_call markup, or JSON fallback."""
    # 1. Native OpenAI / LM Studio tool_calls array
    tool_calls = message.get("tool_calls") or []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        if fn.get("name") == expected_tool_name or len(tool_calls) == 1:
            raw_args = fn.get("arguments")
            if isinstance(raw_args, dict):
                return raw_args
            if isinstance(raw_args, str) and raw_args.strip():
                return _strip_reasoning_and_extract_json(raw_args)

    # 2. XML tool_call inside content or reasoning_content (e.g. prism-ml/bonsai-27b)
    candidates = [
        (message.get("content") or "").strip(),
        (message.get("reasoning_content") or "").strip(),
    ]
    for txt in candidates:
        if not txt:
            continue
        xml_args = _parse_xml_tool_call(txt, expected_tool_name=expected_tool_name)
        if xml_args:
            return xml_args

    # 3. JSON object fallback inside content or reasoning_content
    for txt in candidates:
        if not txt:
            continue
        try:
            obj = _strip_reasoning_and_extract_json(txt)
            if isinstance(obj.get("arguments"), dict):
                return obj["arguments"]
            if isinstance(obj.get("arguments"), str):
                return _strip_reasoning_and_extract_json(obj["arguments"])
            return obj
        except LLMInvocationError:
            continue

    raise LLMInvocationError(f"LLM did not return valid tool call arguments for '{expected_tool_name}'.")


def invoke_tool_call(
    system_prompt: str,
    user_prompt: str,
    tool_name: str,
    tool_description: str,
    input_model: type[T],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> T:
    """Invoke the configured LLM using a Strands-compatible structured tool definition and return validated input_model."""
    status = llm_status_info()
    if not status["llm_enabled"]:
        raise LLMNotConfigured(
            "No LLM provider is enabled. Configure LMSTUDIO_ENABLED=true (LM Studio) or BEDROCK_ENABLED=true in .env."
        )

    param_schema = _make_lmstudio_compatible_schema(input_model.model_json_schema())
    provider = status["llm_provider"]

    if provider == "lmstudio":
        base_url = normalize_lmstudio_base_url(settings.lmstudio_base_url)
        endpoint = f"{base_url}/chat/completions"
        model = settings.lmstudio_model_id.strip()
        if not model:
            raise LLMNotConfigured("LMSTUDIO_MODEL_ID is not configured.")

        temp = settings.llm_temperature if temperature is None else temperature
        mtok = settings.llm_max_tokens if max_tokens is None else max_tokens
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temp,
            "max_tokens": mtok,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool_description,
                        "parameters": param_schema,
                    },
                }
            ],
            "tool_choice": "required",
        }

        timeout = httpx.Timeout(settings.lmstudio_timeout, connect=10.0)
        with httpx.Client(timeout=timeout) as client:
            try:
                resp = client.post(endpoint, json=payload)
                if resp.status_code == 400:
                    # Fallback to strict json_schema if server/model does not accept tools
                    return invoke_structured(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        response_model=input_model,
                        schema_name=tool_name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                resp.raise_for_status()
                body = resp.json()
                choices = body.get("choices") or []
                if not choices:
                    raise LLMInvocationError("LM Studio returned no choices for tool call.")
                args = _extract_tool_arguments(choices[0].get("message") or {}, expected_tool_name=tool_name)
            except httpx.ConnectError as exc:
                raise LLMInvocationError(
                    f"Cannot connect to LM Studio at {base_url}. Ensure LM Studio Local Server is running with model '{model}'."
                ) from exc
            except httpx.TimeoutException as exc:
                raise LLMInvocationError(
                    f"LM Studio timed out after {settings.lmstudio_timeout}s waiting for '{model}' on tool '{tool_name}'."
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise LLMInvocationError(
                    f"LM Studio returned HTTP {exc.response.status_code}: {exc.response.text[:300]}"
                ) from exc
    elif provider == "bedrock":
        return invoke_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=input_model,
            schema_name=tool_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        raise LLMNotConfigured(f"Unsupported LLM provider: {provider}")

    try:
        return input_model.model_validate(args)
    except ValidationError as exc:
        raise LLMInvocationError(f"Tool '{tool_name}' arguments failed validation: {exc}") from exc


def _trim_xml_param_edges(raw_val: str) -> str:
    """Trim only the single wrapper newline emitted around XML parameter bodies while preserving Python indentation."""
    val = raw_val or ""
    if val.startswith("\r\n"):
        val = val[2:]
    elif val.startswith("\n"):
        val = val[1:]
    if val.endswith("\r\n"):
        val = val[:-2]
    elif val.endswith("\n"):
        val = val[:-1]
    return val


def parse_all_xml_tool_calls(text: str) -> list[dict[str, Any]]:
    """Extract all XML-style tool calls (<function=name><parameter=k>v</parameter>...</function>) preserving code indentation."""
    if not text or "<function=" not in text:
        return []
    blocks = re.findall(r"<function=([^>\s]+)\s*>(.*?)</function>", text, flags=re.S | re.I)
    if not blocks:
        m = re.search(r"<function=([^>\s]+)\s*>(.*)$", text, flags=re.S | re.I)
        if m:
            blocks = [(m.group(1), m.group(2))]
    calls: list[dict[str, Any]] = []
    for fn_name, fn_body in blocks:
        params = re.findall(r"<parameter=([^>\s]+)\s*>(.*?)</parameter>", fn_body, flags=re.S | re.I)
        args: dict[str, Any] = {}
        for k, v in params:
            key = k.strip()
            raw = _trim_xml_param_edges(v)
            # Preserve multiline text/code/markdown verbatim; only coerce simple scalar/json params
            if key in {"content", "target", "replacement", "command", "summary_notes", "master_md"}:
                args[key] = raw
            else:
                args[key] = _coerce_param_value(raw)
        calls.append({"name": fn_name.strip(), "arguments": args})
    return calls


def invoke_agent_turn(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: str = "auto",
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Run one LLM turn with OpenAI/LM Studio function tools and return {'text': str, 'tool_calls': [{'name', 'arguments'}]}."""
    status = llm_status_info()
    if not status["llm_enabled"]:
        raise LLMNotConfigured("No LLM provider is enabled.")

    provider = status["llm_provider"]
    if provider != "lmstudio":
        raise LLMNotConfigured(f"Multi-turn agent tools currently require LM Studio (active provider: {provider}).")

    base_url = normalize_lmstudio_base_url(settings.lmstudio_base_url)
    endpoint = f"{base_url}/chat/completions"
    model = settings.lmstudio_model_id.strip()
    temp = settings.llm_temperature if temperature is None else temperature
    mtok = settings.llm_max_tokens if max_tokens is None else max_tokens

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temp,
        "max_tokens": mtok,
        "tools": tools,
        "tool_choice": tool_choice,
        "stream": True,
    }

    timeout = httpx.Timeout(settings.lmstudio_timeout, connect=10.0)
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tc_accum: dict[int, dict[str, str]] = {}

    with _lmstudio_slot():
        with httpx.Client(timeout=timeout) as client:
            try:
                with client.stream("POST", endpoint, json=payload) as resp:
                    resp.raise_for_status()
                    for raw_line in resp.iter_lines():
                        if not raw_line or not raw_line.startswith("data: "):
                            continue
                        data_str = raw_line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        if delta.get("content"):
                            content_parts.append(str(delta["content"]))
                        if delta.get("reasoning_content"):
                            reasoning_parts.append(str(delta["reasoning_content"]))
                        for tc_delta in (delta.get("tool_calls") or []):
                            idx = int(tc_delta.get("index", 0))
                            slot = tc_accum.setdefault(idx, {"name": "", "arguments": ""})
                            fn = tc_delta.get("function") or {}
                            if fn.get("name"):
                                slot["name"] += str(fn["name"])
                            if fn.get("arguments"):
                                slot["arguments"] += str(fn["arguments"])
            except httpx.ConnectError as exc:
                raise LLMInvocationError(f"Cannot connect to LM Studio at {base_url}.") from exc
            except httpx.TimeoutException as exc:
                raise LLMInvocationError(f"LM Studio timed out after {settings.lmstudio_timeout}s.") from exc
            except httpx.HTTPStatusError as exc:
                raise LLMInvocationError(f"LM Studio HTTP {exc.response.status_code}: {exc.response.text[:300]}") from exc

    content = "".join(content_parts).strip()
    reasoning = "".join(reasoning_parts).strip()
    message = {
        "role": "assistant",
        "content": content,
        "reasoning_content": reasoning,
        "tool_calls": [
            {"function": {"name": tc_accum[i]["name"], "arguments": tc_accum[i]["arguments"]}}
            for i in sorted(tc_accum)
            if tc_accum[i]["name"]
        ],
    }

    extracted_calls: list[dict[str, Any]] = []
    # 1. Native OpenAI/LM Studio tool_calls
    for tc in (message.get("tool_calls") or []):
        fn = tc.get("function") or {}
        name = (fn.get("name") or "").strip()
        raw_args = fn.get("arguments")
        if isinstance(raw_args, dict):
            args = raw_args
        elif isinstance(raw_args, str) and raw_args.strip():
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = _strip_reasoning_and_extract_json(raw_args)
        else:
            args = {}
        if name:
            extracted_calls.append({"name": name, "arguments": args})

    # 2. XML tool calls emitted by prism-ml/bonsai-27b in content or reasoning_content
    if not extracted_calls:
        for txt in (content, reasoning):
            xml_calls = parse_all_xml_tool_calls(txt)
            if xml_calls:
                extracted_calls.extend(xml_calls)
                break

    visible_text = content or re.sub(r"<tool_call>.*?</tool_call>", "", reasoning, flags=re.S | re.I).strip()
    return {
        "text": visible_text,
        "tool_calls": extracted_calls,
        "raw_message": message,
    }
