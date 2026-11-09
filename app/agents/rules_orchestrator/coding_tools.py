"""Crush-inspired scoped coding-agent tool interfaces."""
from __future__ import annotations

import hashlib
from pydantic import BaseModel, Field

from app.tools.execution_tools import run_python as exec_run_python
from app.tools.workspace_tools import read_workspace_file, write_workspace_file


class WorkspacePath(BaseModel):
    claim_id: str
    relative_path: str = Field(min_length=1)
    run_id: str | None = None


def read_file(path: WorkspacePath) -> str:
    """Resolve relative path under claim workspace; enforce role ACL and max bytes."""
    return read_workspace_file(path.claim_id, path.relative_path, run_id=path.run_id)


def write_file(path: WorkspacePath, content: str, expected_previous_hash: str | None = None) -> dict[str, str | int]:
    """Write atomically under scoped root, require read-before-write for existing file."""
    return write_workspace_file(
        claim_id=path.claim_id,
        relative_path=path.relative_path,
        content=content,
        expected_hash=expected_previous_hash,
        run_id=path.run_id,
    )


def edit_file(path: WorkspacePath, old_text: str, new_text: str, expected_hash: str | None = None) -> dict[str, str | int]:
    """Exact-match replacement; if match count != 1 or hash changed, fail and require reread."""
    current_content = read_file(path)
    if expected_hash:
        current_hash = hashlib.sha256(current_content.encode("utf-8")).hexdigest()
        if current_hash != expected_hash:
            raise ValueError(f"File hash changed: expected {expected_hash}, got {current_hash}")

    count = current_content.count(old_text)
    if count == 0:
        raise ValueError("Target old_text not found in file")
    if count > 1:
        raise ValueError(f"Target old_text occurs {count} times; exact single match required")

    updated = current_content.replace(old_text, new_text, 1)
    return write_file(path, updated, expected_previous_hash=expected_hash)


def run_python(claim_id: str, script_path: str, timeout_seconds: int = 180, run_id: str | None = None) -> dict:
    """Dispatch isolated non-root execution via SandboxClient."""
    return exec_run_python(claim_id, script_path, timeout_seconds=timeout_seconds, run_id=run_id)
