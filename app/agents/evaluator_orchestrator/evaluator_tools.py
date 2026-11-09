"""Read-only verification tool interfaces."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from app.services.sandbox_client import default_sandbox
from app.tools.artifact_tools import read_artifact as base_read_artifact
from app.tools.workspace_tools import get_claim_workspace_dir


def inspect_artifact(artifact_id: str) -> dict[str, Any]:
    """Resolve immutable artifact version and return bounded contents + checksum."""
    return base_read_artifact(artifact_id, requester_role="evaluator")


def rerun_artifact_independently(claim_id: str, run_id: str, source_dir: str | Path | None = None) -> dict[str, Any]:
    """Copy published script to a clean temporary isolated workspace and execute independently."""
    ws_dir = get_claim_workspace_dir(claim_id, run_id=run_id)
    script_file = ws_dir / "analysis.py"

    if not script_file.exists():
        raise FileNotFoundError(f"Analysis script not found in claim workspace {claim_id}")

    # Create clean temp sandbox
    with tempfile.TemporaryDirectory() as clean_sandbox_dir:
        clean_sandbox = Path(clean_sandbox_dir)
        clean_script = clean_sandbox / "analysis.py"
        clean_script.write_text(script_file.read_text(encoding="utf-8"), encoding="utf-8")

        # Execute
        result = default_sandbox.execute(
            run_id=run_id,
            claim_id=claim_id,
            script_path="analysis.py",
            workspace_dir=clean_sandbox,
            source_input_dir=source_dir or Path("runtime/sample_pbrer_data").resolve(),
        )
        return result
