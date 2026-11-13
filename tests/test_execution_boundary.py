from __future__ import annotations

import pytest
from app.runtime.execution_boundary import (
    ExecutionBoundaryUnavailable, LocalDevelopmentExecutor, get_generation_executor,
)


def test_production_local_executor_is_blocked(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACEWISE_ENV", "production")
    with pytest.raises(ExecutionBoundaryUnavailable, match="forbidden outside development"):
        LocalDevelopmentExecutor().execute(
            generation_id="g", script_path="reproduce_section.py", workspace_dir=tmp_path,
            source_input_dir=tmp_path, generation_context_path=tmp_path / "context.json",
        )


def test_isolated_worker_fails_closed_until_connected(monkeypatch):
    monkeypatch.setenv("TRACEWISE_GENERATION_EXECUTOR", "isolated")
    worker = get_generation_executor()
    assert worker.__class__.__name__ == "IsolatedWorkerExecutor"
    with pytest.raises(ExecutionBoundaryUnavailable, match="not connected"):
        worker.execute()
