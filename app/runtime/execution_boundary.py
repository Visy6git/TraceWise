"""Separate code-authoring, validation and future-year calculation boundaries.

The existing SandboxClient in this repository currently invokes subprocess on the
API/worker host even when its backend label is non-empty. This wrapper therefore
allows it only with an explicit local-development opt-in. Production MUST inject
an isolated executor (ECS/Fargate task, locked-down container runtime, or other
isolated service). No silent host fallback is allowed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol


class ExecutionBoundaryUnavailable(RuntimeError):
    pass


class BlueprintExecutor(Protocol):
    def execute(self, *, generation_id: str, script_path: str, workspace_dir: Path,
                source_input_dir: Path, generation_context_path: Path) -> dict[str, Any]: ...


class LocalDevelopmentExecutor:
    """Explicitly unsafe local-only adapter for synthetic fixtures, never production PHI."""
    def execute(self, *, generation_id: str, script_path: str, workspace_dir: Path,
                source_input_dir: Path, generation_context_path: Path) -> dict[str, Any]:
        if os.environ.get("TRACEWISE_ENV", "development").lower() != "development":
            raise ExecutionBoundaryUnavailable("Local development executor is forbidden outside development")
        if os.environ.get("TRACEWISE_ALLOW_LOCAL_GENERATION_EXECUTION", "false").lower() != "true":
            raise ExecutionBoundaryUnavailable(
                "Set TRACEWISE_ALLOW_LOCAL_GENERATION_EXECUTION=true only for synthetic local test data."
            )
        # Stage 2 sandbox client is reused only as a local-development convenience.
        # It is NOT container isolation. Never use this branch for real patient-level data.
        from app.services.sandbox_client import default_sandbox
        return default_sandbox.execute(
            run_id=generation_id, claim_id="section-16-3", script_path=script_path,
            workspace_dir=workspace_dir, source_input_dir=source_input_dir,
            limits={"timeout_seconds": 900, "max_output_bytes": 2_000_000},
        )


class IsolatedWorkerExecutor:
    """Connection placeholder for isolated AWS execution worker.

    Implement authenticated submission to a dedicated ECS/Fargate task or a
    Step Functions task. Pass only the generation-scoped source snapshot, pinned
    image reference, approved blueprint hash and resource limits. Return job ID,
    exit status and bounded output references. No credentials are passed to the
    generated script. This class intentionally fails closed until connected.
    """
    def execute(self, **kwargs: Any) -> dict[str, Any]:
        raise ExecutionBoundaryUnavailable(
            "Isolated generation worker is not connected. Configure the ECS/Fargate execution adapter; refusing host execution."
        )


def get_generation_executor() -> BlueprintExecutor:
    backend = os.environ.get("TRACEWISE_GENERATION_EXECUTOR", "isolated").lower()
    if backend == "local-development":
        return LocalDevelopmentExecutor()
    if backend in {"isolated", "ecs", "fargate"}:
        return IsolatedWorkerExecutor()
    raise ExecutionBoundaryUnavailable(f"Unsupported generation executor: {backend}")
