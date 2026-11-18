from __future__ import annotations
import threading
from typing import Callable


class PauseController:
    """Thread-safe cooperative pause controller for orchestrator runs.

    Starts in an unpaused (set) state. Calling `pause()` clears the internal
    event so any subsequent `wait_if_paused()` calls block until `resume()` is called.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._event.set()
        self._is_paused = False
        self._lock = threading.Lock()

    def pause(self) -> None:
        with self._lock:
            self._is_paused = True
            self._event.clear()

    def resume(self) -> None:
        with self._lock:
            self._is_paused = False
            self._event.set()

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def wait_if_paused(self, timeout: float | None = None) -> bool:
        """Blocks if paused until resume() is called. Returns True if unpaused/resumed."""
        return self._event.wait(timeout=timeout)


PauseCheck = Callable[[], None]
