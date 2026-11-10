"""Context window management, loop detection, and chat compaction for the harness."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.harness.config import HarnessConfig
from app.harness.events import StreamEventType, TokenUsage
from app.harness.prompts import get_compression_prompt, get_system_prompt
from app.harness.text import count_tokens

if TYPE_CHECKING:
    from app.harness.llm_client import LLMClient
    from app.harness.tools.base import Tool


class LoopDetector:
    def __init__(self, max_exact_repeats: int = 3, max_cycle_length: int = 3):
        self.max_exact_repeats = max_exact_repeats
        self.max_cycle_length = max_cycle_length
        self._history: deque[str] = deque(maxlen=24)

    def record_action(self, action_type: str, **details: Any) -> None:
        parts = [action_type]
        if action_type == "tool_call":
            parts.append(str(details.get("tool_name", "")))
            args = details.get("args", {})
            if isinstance(args, dict):
                for k in sorted(args.keys()):
                    parts.append(f"{k}={args[k]}")
        elif action_type == "response":
            parts.append(str(details.get("text", "")))
        self._history.append("|".join(parts))

    def check_for_loop(self) -> str | None:
        if len(self._history) < 2:
            return None

        if len(self._history) >= self.max_exact_repeats:
            recent = list(self._history)[-self.max_exact_repeats :]
            if len(set(recent)) == 1:
                return f"Same action repeated {self.max_exact_repeats} times"

        if len(self._history) >= self.max_cycle_length * 2:
            history = list(self._history)
            for cycle_len in range(2, min(self.max_cycle_length + 1, len(history) // 2 + 1)):
                recent = history[-cycle_len * 2 :]
                if recent[:cycle_len] == recent[cycle_len:]:
                    return f"Detected repeating cycle of length {cycle_len}"
        return None

    def clear(self) -> None:
        self._history.clear()


@dataclass
class MessageItem:
    role: str
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    token_count: int | None = None
    pruned_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"role": self.role}
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
            result["content"] = self.content if self.content else None
        else:
            result["content"] = self.content or ""
        return result


class ContextManager:
    PRUNE_PROTECT_TOKENS = 18_000
    PRUNE_MINIMUM_TOKENS = 8_000

    def __init__(self, config: HarnessConfig, tools: list[Tool] | None = None) -> None:
        self.config = config
        self._model_name = config.effective_model_name()
        self._system_prompt = get_system_prompt(config, tools)
        self._messages: list[MessageItem] = []
        self._latest_usage = TokenUsage()
        self.total_usage = TokenUsage()

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def add_user_message(self, content: str) -> None:
        self._messages.append(
            MessageItem(
                role="user",
                content=content,
                token_count=count_tokens(content, self._model_name),
            )
        )

    def add_assistant_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        text = content or ""
        self._messages.append(
            MessageItem(
                role="assistant",
                content=text,
                token_count=count_tokens(text, self._model_name),
                tool_calls=tool_calls or [],
            )
        )

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self._messages.append(
            MessageItem(
                role="tool",
                content=content,
                tool_call_id=tool_call_id,
                token_count=count_tokens(content, self._model_name),
            )
        )

    def get_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        for item in self._messages:
            messages.append(item.to_dict())
        return messages

    def needs_compression(self) -> bool:
        context_limit = self.config.model.context_window
        current_tokens = self._latest_usage.total_tokens
        return current_tokens > (context_limit * 0.8)

    def set_latest_usage(self, usage: TokenUsage) -> None:
        self._latest_usage = usage

    def add_usage(self, usage: TokenUsage) -> None:
        self.total_usage += usage

    def prune_tool_outputs(self) -> int:
        user_message_count = sum(1 for msg in self._messages if msg.role == "user")
        if user_message_count < 1:
            return 0

        total_tokens = 0
        pruned_tokens = 0
        to_prune: list[MessageItem] = []
        for msg in reversed(self._messages):
            if msg.role == "tool" and msg.tool_call_id:
                if msg.pruned_at:
                    break
                tokens = msg.token_count or count_tokens(msg.content, self._model_name)
                total_tokens += tokens
                if total_tokens > self.PRUNE_PROTECT_TOKENS:
                    pruned_tokens += tokens
                    to_prune.append(msg)

        if pruned_tokens < self.PRUNE_MINIMUM_TOKENS:
            return 0

        for msg in to_prune:
            msg.content = "[Older tool output cleared to save context]"
            msg.token_count = count_tokens(msg.content, self._model_name)
            msg.pruned_at = datetime.now()
        return len(to_prune)

    def replace_with_summary(self, summary: str) -> None:
        self._messages = [
            MessageItem(
                role="user",
                content=(
                    "# Previous Harness Work Summary\n"
                    "Resume from here without repeating completed steps:\n\n"
                    f"{summary}"
                ),
                token_count=count_tokens(summary, self._model_name),
            )
        ]

    def clear(self) -> None:
        self._messages = []


class ChatCompactor:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def _format_history(self, messages: list[dict[str, Any]]) -> str:
        output: list[str] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content") or ""
            if role == "system":
                continue
            if role == "tool":
                preview = content[:1500] + ("\n...[truncated]" if len(content) > 1500 else "")
                output.append(f"[Tool Result {msg.get('tool_call_id', '')}]:\n{preview}")
            elif role == "assistant":
                if content:
                    output.append(f"Assistant: {content[:1500]}")
                if msg.get("tool_calls"):
                    calls = [tc.get("function", {}).get("name", "?") for tc in msg["tool_calls"]]
                    output.append(f"Assistant called tools: {', '.join(calls)}")
            else:
                output.append(f"User: {content[:1500]}")
        return "\n\n".join(output)

    async def compress(self, context_manager: ContextManager) -> tuple[str | None, TokenUsage | None]:
        messages = context_manager.get_messages()
        if len(messages) < 3:
            return None, None
        compaction_messages = [
            {"role": "system", "content": get_compression_prompt()},
            {"role": "user", "content": self._format_history(messages)},
        ]
        summary = ""
        usage: TokenUsage | None = None
        async for event in self.client.chat_completion(compaction_messages, stream=False):
            if event.type == StreamEventType.MESSAGE_COMPLETE:
                usage = event.usage
                if event.text_delta:
                    summary += event.text_delta.content
        if not summary:
            return None, None
        return summary, usage

