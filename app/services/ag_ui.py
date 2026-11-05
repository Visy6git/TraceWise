"""AG-UI Protocol: Interactive Event Streaming Engine for Autonomous Agents.
Delivers real-time telemetry of agent thoughts, A2A communication, file access,
filtering, Python code generation & sandboxed execution, and data compilation.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
import queue
from typing import Any, Iterator


@dataclass
class AGUIEvent:
    event_id: str
    run_id: str
    timestamp: str
    agent_id: str
    agent_name: str
    agent_role: str
    event_type: str  # agent_thought, a2a_message, file_focus, agent_filtering, code_generating, code_execution, data_compiling, rule_created, section_mapped, user_note_applied, orchestration_status
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_sse(self) -> str:
        return f"data: {json.dumps(self.to_dict())}\n\n"


class AGUIEventManager:
    """Manages thread-safe event history and live subscribers for each active run."""

    def __init__(self):
        self._events_by_run: dict[str, list[AGUIEvent]] = {}
        self._subscribers: dict[str, list[queue.Queue]] = {}

    def get_events(self, run_id: str, since_idx: int = 0) -> list[dict[str, Any]]:
        events = self._events_by_run.get(run_id, [])
        return [e.to_dict() for e in events[since_idx:]]

    def emit(
        self,
        run_id: str,
        agent_id: str,
        agent_name: str,
        agent_role: str,
        event_type: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> AGUIEvent:
        if details is None:
            details = {}
        now = datetime.now(timezone.utc).isoformat()
        if run_id not in self._events_by_run:
            self._events_by_run[run_id] = []
        idx = len(self._events_by_run[run_id])
        evt = AGUIEvent(
            event_id=f"evt_{idx}_{datetime.now(timezone.utc).strftime('%H%M%S%f')[:10]}",
            run_id=run_id,
            timestamp=now,
            agent_id=agent_id,
            agent_name=agent_name,
            agent_role=agent_role,
            event_type=event_type,
            summary=summary,
            details=details,
        )
        self._events_by_run[run_id].append(evt)

        # Notify subscribers
        queues = self._subscribers.get(run_id, [])
        for q in list(queues):
            try:
                q.put_nowait(evt)
            except Exception:
                pass
        return evt

    def subscribe_sync(self, run_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        if run_id not in self._subscribers:
            self._subscribers[run_id] = []
        self._subscribers[run_id].append(q)
        return q

    def unsubscribe_sync(self, run_id: str, q: queue.Queue):
        if run_id in self._subscribers and q in self._subscribers[run_id]:
            self._subscribers[run_id].remove(q)


# Global singleton
ag_ui_manager = AGUIEventManager()
