"""AG-UI Protocol: Interactive Event Streaming Engine for Autonomous Agents.
Delivers real-time telemetry of agent thoughts, A2A communication, file access,
filtering, Python code generation & sandboxed execution, and data compilation.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
import queue
import threading
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
        self._lock = threading.Lock()

    def get_events(self, run_id: str, since_idx: int = 0) -> list[dict[str, Any]]:
        with self._lock:
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
        with self._lock:
            events = self._events_by_run.setdefault(run_id, [])
            idx = len(events)
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
            events.append(evt)
            queues = list(self._subscribers.get(run_id, []))
        for subscriber in queues:
            subscriber.put_nowait(evt)
        return evt

    def subscribe_sync(self, run_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(run_id, []).append(q)
        return q

    def unsubscribe_sync(self, run_id: str, q: queue.Queue):
        with self._lock:
            if run_id in self._subscribers and q in self._subscribers[run_id]:
                self._subscribers[run_id].remove(q)


# Global singleton
ag_ui_manager = AGUIEventManager()
