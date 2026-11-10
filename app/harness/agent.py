"""Core async agentic harness loop reused across Stage 1 exploration and Stage 2 rules."""
from __future__ import annotations

import json
from typing import AsyncGenerator

from app.harness.approval import ApprovalManager
from app.harness.config import HarnessConfig
from app.harness.context import ChatCompactor, ContextManager, LoopDetector
from app.harness.events import AgentEvent, StreamEventType, TokenUsage, ToolCall
from app.harness.hooks import HookSystem
from app.harness.llm_client import LLMClient
from app.harness.tools.registry import ToolRegistry, create_default_registry


class HarnessAgent:
    """Bounded, autonomous coding & data-exploration agent harness."""

    def __init__(
        self,
        config: HarnessConfig,
        llm_client: LLMClient | None = None,
        hook_system: HookSystem | None = None,
    ) -> None:
        self.config = config
        self.cwd = config.resolved_cwd()
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.client = llm_client or LLMClient(config)
        self.tool_registry: ToolRegistry = create_default_registry(config)
        self.context_manager = ContextManager(config, self.tool_registry.get_tools())
        self.compactor = ChatCompactor(self.client)
        self.loop_detector = LoopDetector()
        self.hook_system = hook_system or HookSystem()
        self.approval_manager = ApprovalManager(
            approval_policy=config.approval,
            cwd=self.cwd,
            readonly_dirs=config.resolved_readonly_dirs(),
        )

    async def __aenter__(self) -> HarnessAgent:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.client.close()

    async def run(self, goal: str) -> AsyncGenerator[AgentEvent, None]:
        yield AgentEvent.agent_start(goal)
        self.context_manager.add_user_message(goal)
        final_response: str | None = None

        for turn in range(1, self.config.max_turns + 1):
            if self.context_manager.needs_compression():
                self.context_manager.prune_tool_outputs()
                summary, usage = await self.compactor.compress(self.context_manager)
                if summary:
                    self.context_manager.replace_with_summary(summary)
                if usage:
                    self.context_manager.add_usage(usage)

            response_text = ""
            tool_calls: list[ToolCall] = []
            usage: TokenUsage | None = None
            tool_schemas = self.tool_registry.get_schemas()

            async for event in self.client.chat_completion(
                self.context_manager.get_messages(),
                tools=tool_schemas or None,
                stream=False,
            ):
                if event.type == StreamEventType.TEXT_DELTA and event.text_delta:
                    content = event.text_delta.content
                    response_text += content
                    yield AgentEvent.text_delta(content)
                elif event.type == StreamEventType.TOOL_CALL_COMPLETE and event.tool_call:
                    tool_calls.append(event.tool_call)
                elif event.type == StreamEventType.ERROR:
                    yield AgentEvent.agent_error(event.error or "Unknown LLM error")
                    return
                elif event.type == StreamEventType.MESSAGE_COMPLETE:
                    usage = event.usage

            formatted_tool_calls = [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {
                        "name": tc.name or "",
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in tool_calls
            ]

            self.context_manager.add_assistant_message(
                response_text,
                formatted_tool_calls if formatted_tool_calls else None,
            )

            if response_text:
                yield AgentEvent.text_complete(response_text)
                final_response = response_text
                self.loop_detector.record_action("response", text=response_text)

            if usage:
                self.context_manager.set_latest_usage(usage)
                self.context_manager.add_usage(usage)

            if not tool_calls:
                break

            tool_results: list[tuple[str, str]] = []
            for tc in tool_calls:
                self.loop_detector.record_action(
                    "tool_call", tool_name=tc.name or "", args=tc.arguments
                )
                yield AgentEvent.tool_call_start(tc.call_id, tc.name or "", tc.arguments)
                result = await self.tool_registry.invoke(
                    tc.name or "",
                    tc.arguments,
                    self.cwd,
                    self.hook_system,
                    self.approval_manager,
                )
                yield AgentEvent.tool_call_complete(tc.call_id, tc.name or "", result)
                tool_results.append((tc.call_id, result.to_model_output()))

            for call_id, model_output in tool_results:
                self.context_manager.add_tool_result(call_id, model_output)

            self.context_manager.prune_tool_outputs()

            loop_error = self.loop_detector.check_for_loop()
            if loop_error:
                loop_msg = (
                    f"Loop guard triggered ({loop_error}). "
                    "Do not repeat identical commands; summarize what succeeded or adjust parameters."
                )
                self.context_manager.add_user_message(loop_msg)
                self.loop_detector.clear()

        yield AgentEvent.agent_end(final_response, self.context_manager.total_usage)

