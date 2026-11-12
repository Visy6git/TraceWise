"""Cooperative, thread-safe pause signalling for in-flight stage runs.

Stage orchestrators run in background threads. A pause is a request the running
orchestrator observes at a safe boundary (between claims) and then stops cleanly,
leaving completed work intact so the stage can be resumed later. This is a process-
local signal (a TODO for a durable/distributed deployment is a shared store).
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_pause_requested: set[str] = set()


def request_pause(run_id: str) -> None:
    """Ask the orchestrator processing `run_id` to stop at its next safe boundary."""
    with _lock:
        _pause_requested.add(run_id)


def is_pause_requested(run_id: str) -> bool:
    with _lock:
        return run_id in _pause_requested


def clear_pause(run_id: str) -> bool:
    """Clear and return whether a pause was pending for `run_id`."""
    with _lock:
        if run_id in _pause_requested:
            _pause_requested.discard(run_id)
            return True
        return False
