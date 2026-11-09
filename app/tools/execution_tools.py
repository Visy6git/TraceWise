"""Sandbox execution tools. This module intentionally delegates to SandboxClient."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.services.sandbox_client import SandboxClient, default_sandbox
from app.tools.workspace_tools import get_claim_workspace_dir, validate_workspace_path


def run_python(
    claim_id: str,
    relative_script_path: str,
    timeout_seconds: int = 180,
    run_id: str | None = None,
    source_dir: str | Path | None = None,
    client: SandboxClient | None = None,
) -> dict[str, Any]:
    script_rel = validate_workspace_path(relative_script_path)
    ws_dir = get_claim_workspace_dir(claim_id, run_id)
    sandbox = client or default_sandbox

    return sandbox.execute(
        run_id=run_id or "local",
        claim_id=claim_id,
        script_path=script_rel,
        limits={"timeout_seconds": timeout_seconds},
        workspace_dir=ws_dir,
        source_input_dir=source_dir,
    )


def run_pytest(
    claim_id: str,
    tests_path: str = "tests",
    timeout_seconds: int = 60,
    run_id: str | None = None,
    client: SandboxClient | None = None,
) -> dict[str, Any]:
    test_rel = validate_workspace_path(tests_path)
    ws_dir = get_claim_workspace_dir(claim_id, run_id)
    sandbox = client or default_sandbox

    import sys
    import subprocess
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": f"{os.path.abspath('.')};{ws_dir}",
    }

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(ws_dir / test_rel), "-q"],
            cwd=str(ws_dir),
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "claim_id": claim_id,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "passed": proc.returncode == 0,
        }
    except Exception as e:
        return {
            "claim_id": claim_id,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
            "passed": False,
        }
