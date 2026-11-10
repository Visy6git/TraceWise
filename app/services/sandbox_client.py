"""Fail-closed subprocess verification client with Windows path normalization."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from app.harness.paths import strip_extended_prefix


class SandboxUnavailable(RuntimeError):
    pass


class SandboxExecutionError(RuntimeError):
    pass


class SandboxClient:
    def __init__(self, backend: str | None = None, required: bool = True):
        self.backend = backend if backend is not None else os.environ.get("SANDBOX_BACKEND", "local_subprocess")
        self.required = required if required is not None else (
            os.environ.get("SANDBOX_REQUIRED", "true").lower() == "true"
        )

    def execute(
        self,
        run_id: str,
        claim_id: str,
        script_path: str,
        limits: dict[str, Any] | None = None,
        workspace_dir: str | Path | None = None,
        source_input_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        if self.required and self.backend in {"disabled", "", None}:
            raise SandboxUnavailable("Sandbox backend is required; refusing host execution")

        limits = limits or {}
        timeout_seconds = limits.get("timeout_seconds", int(os.environ.get("MAX_EXECUTION_SECONDS", "180")))
        max_output_bytes = limits.get("max_output_bytes", int(os.environ.get("MAX_OUTPUT_BYTES", "1048576")))

        cwd = strip_extended_prefix(Path(workspace_dir or ".")).resolve()
        script_file = (cwd / script_path).resolve()
        if not script_file.exists():
            script_file = strip_extended_prefix(Path(script_path)).resolve()
            if not script_file.exists():
                raise FileNotFoundError(f"Script not found at {script_path}")

        src_dir = strip_extended_prefix(Path(source_input_dir)).resolve() if source_input_dir else cwd
        venv_bin = str(Path(sys.executable).resolve().parent)
        existing_path = os.environ.get("PATH", "")
        clean_path = f"{venv_bin}{os.pathsep}{existing_path}" if existing_path else venv_bin

        clean_env = {
            k: v
            for k, v in os.environ.items()
            if k.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT"}
        }
        clean_env.update(
            {
                "PATH": clean_path,
                "PYTHONPATH": os.path.abspath("."),
                "PYTHONIOENCODING": "utf-8",
                "SOURCE_INPUT_DIR": str(src_dir),
                "CLAIM_WORKSPACE_DIR": str(cwd),
                "CLAIM_ID": claim_id,
                "RUN_ID": run_id,
            }
        )

        start_time = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, str(script_file)],
                cwd=str(cwd),
                env=clean_env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            elapsed = time.time() - start_time
            stdout = proc.stdout[:max_output_bytes]
            stderr = proc.stderr[:max_output_bytes]
            exit_code = proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            elapsed = time.time() - start_time
            stdout = (exc.stdout or "")[:max_output_bytes] if isinstance(exc.stdout, str) else ""
            stderr = f"Execution timed out after {timeout_seconds} seconds"
            exit_code = -1
            timed_out = True

        result_json_path = cwd / "result.json"
        result_data = None
        if result_json_path.exists():
            try:
                result_data = json.loads(result_json_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        return {
            "run_id": run_id,
            "claim_id": claim_id,
            "script_path": script_path,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "execution_seconds": round(elapsed, 3),
            "timed_out": timed_out,
            "result_data": result_data,
            "status": "success" if exit_code == 0 else "error",
        }


default_sandbox = SandboxClient()
