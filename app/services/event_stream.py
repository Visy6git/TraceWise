"""AG-UI 1.0 SSE serialization and durable event broker."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, AsyncIterator


def agui_event(event_type: str, **fields: Any) -> dict[str, Any]:
    """Construct an AG-UI event payload. Keep app-specific telemetry under CUSTOM.value."""
    event = {"type": event_type, **fields}
    event.setdefault("timestamp", int(time.time() * 1000))
    return event


def encode_sse(event: dict[str, Any], event_id: str | None = None) -> str:
    """AG-UI events are JSON data frames over SSE; do not emit private reasoning events."""
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append("data: " + json.dumps(event, separators=(",", ":"), ensure_ascii=False))
    return "\n".join(lines) + "\n\n"


class EventBroker:
    def __init__(self):
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._listeners: dict[str, list[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            history = self._history.setdefault(run_id, [])
            event["_sequence_id"] = str(len(history) + 1)
            history.append(event)
            listeners = list(self._listeners.get(run_id, []))

        # Stage execution runs in a worker thread, while SSE generators live on
        # the event loop. asyncio.Queue is not thread-safe, so bridge the put
        # onto the loop with call_soon_threadsafe to guarantee live delivery.
        loop = self._loop
        for q in listeners:
            if loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(q.put_nowait, event)
                    continue
                except RuntimeError:
                    pass
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def emit_stage_update(self, run_id: str, stage: str, status: str, progress: int = 0, attempt_id: str | None = None) -> None:
        evt = agui_event(
            "CUSTOM",
            threadId=run_id,
            runId=run_id,
            name="tracewise.stage",
            value={
                "stage": stage,
                "status": status,
                "progress": progress,
                "attemptId": attempt_id or f"{stage}-attempt-1",
            },
        )
        self.publish(run_id, evt)

    def emit_activity(
        self,
        run_id: str,
        stage: str,
        title: str,
        detail: str,
        kind: str = "tool",
        agent: str | None = None,
        source: str | None = None,
        artifact: str | None = None,
        status: str = "done",
    ) -> None:
        evt = agui_event(
            "CUSTOM",
            threadId=run_id,
            runId=run_id,
            name="tracewise.activity",
            value={
                "stage": stage,
                "title": title,
                "detail": detail,
                "kind": kind,
                "agent": agent,
                "source": source,
                "artifact": artifact,
                "status": status,
                "time": time.strftime("%H:%M:%S", time.localtime()),
            },
        )
        self.publish(run_id, evt)

    def emit_artifact_update(self, run_id: str, artifact_id: str, logical_path: str, version: int, sha256: str, claim_id: str | None = None, status: str = "ready") -> None:
        evt = agui_event(
            "CUSTOM",
            threadId=run_id,
            runId=run_id,
            name="tracewise.artifact",
            value={
                "artifactId": artifact_id,
                "logicalPath": logical_path,
                "version": version,
                "sha256": sha256,
                "claimId": claim_id,
                "status": status,
            },
        )
        self.publish(run_id, evt)

    def emit_claim_update(self, run_id: str, claim_id: str, section_id: str, status: str, claim_version: int = 1) -> None:
        evt = agui_event(
            "CUSTOM",
            threadId=run_id,
            runId=run_id,
            name="tracewise.claim",
            value={
                "claimId": claim_id,
                "sectionId": section_id,
                "status": status,
                "claimVersion": claim_version,
            },
        )
        self.publish(run_id, evt)

    def emit_subagent_start(self, run_id: str, stage: str, subagent_id: str, name: str, role: str, detail: str = "") -> None:
        self.publish(run_id, agui_event(
            "SUBAGENT_STARTED",
            threadId=run_id,
            runId=run_id,
            subagentId=subagent_id,
            subagentRunId=subagent_id,
            name=name,
            role=role,
            stage=stage,
            detail=detail,
        ))

    def emit_subagent_finish(self, run_id: str, stage: str, subagent_id: str, name: str, claims: int = 0, detail: str = "") -> None:
        self.publish(run_id, agui_event(
            "SUBAGENT_FINISHED",
            threadId=run_id,
            runId=run_id,
            subagentId=subagent_id,
            subagentRunId=subagent_id,
            name=name,
            stage=stage,
            claims=claims,
            detail=detail,
        ))

    def emit_subagent_error(self, run_id: str, stage: str, subagent_id: str, name: str, message: str) -> None:
        self.publish(run_id, agui_event(
            "SUBAGENT_ERROR",
            threadId=run_id,
            runId=run_id,
            subagentId=subagent_id,
            subagentRunId=subagent_id,
            name=name,
            stage=stage,
            message=message,
        ))

    def emit_run_error(self, run_id: str, stage: str, message: str) -> None:
        self.publish(run_id, agui_event(
            "RUN_ERROR",
            threadId=run_id,
            runId=run_id,
            stage=stage,
            message=message,
        ))

    def emit_tool_call(self, run_id: str, tool_name: str, args_summary: dict[str, Any], result_summary: dict[str, Any] | None = None) -> None:
        call_id = f"tool-{int(time.time() * 1000)}"
        self.publish(run_id, agui_event("TOOL_CALL_START", threadId=run_id, runId=run_id, toolCallId=call_id, toolName=tool_name))
        self.publish(run_id, agui_event("TOOL_CALL_ARGS", threadId=run_id, runId=run_id, toolCallId=call_id, args=args_summary))
        if result_summary is not None:
            self.publish(run_id, agui_event("TOOL_CALL_RESULT", threadId=run_id, runId=run_id, toolCallId=call_id, result=result_summary))
        self.publish(run_id, agui_event("TOOL_CALL_END", threadId=run_id, runId=run_id, toolCallId=call_id))

    async def subscribe(self, run_id: str, cursor: str | None = None) -> AsyncIterator[str]:
        # Capture the running loop so off-thread publishers can bridge onto it.
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._listeners.setdefault(run_id, []).append(q)
            history = list(self._history.get(run_id, []))

        try:
            # Replay historical events
            start_idx = 0
            if cursor and cursor.isdigit():
                start_idx = int(cursor)

            for evt in history[start_idx:]:
                seq_id = evt.get("_sequence_id")
                yield encode_sse(evt, event_id=seq_id)

            # Stream live events
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=20.0)
                    seq_id = evt.get("_sequence_id")
                    yield encode_sse(evt, event_id=seq_id)
                except asyncio.TimeoutError:
                    # Keep-alive comment
                    yield ": keep-alive\n\n"
        finally:
            with self._lock:
                if run_id in self._listeners and q in self._listeners[run_id]:
                    self._listeners[run_id].remove(q)


default_broker = EventBroker()


async def stream_run_events(run_id: str, cursor: str | None = None) -> AsyncIterator[str]:
    async for frame in default_broker.subscribe(run_id, cursor):
        yield frame


async def empty_agui_stream(run_id: str) -> AsyncIterator[str]:
    async for frame in stream_run_events(run_id):
        yield frame
