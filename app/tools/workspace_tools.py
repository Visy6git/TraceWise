"""Workspace tools; paths must be logical, relative and stage/claim scoped."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath


def validate_workspace_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not value.strip():
        raise ValueError("Workspace path must be a non-empty relative path without traversal")
    return str(path)


def get_claim_workspace_dir(claim_id: str, run_id: str | None = None, base_root: str | Path | None = None) -> Path:
    root = Path(base_root or os.environ.get("ARTIFACT_ROOT", "./.tracewise-runtime")).resolve()
    if run_id:
        ws = root / "runs" / run_id / "stage_2_rules" / "claims" / claim_id
    else:
        ws = root / "claims" / claim_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def read_workspace_file(claim_id: str, relative_path: str, run_id: str | None = None, base_root: str | Path | None = None) -> str:
    rel = validate_workspace_path(relative_path)
    ws = get_claim_workspace_dir(claim_id, run_id, base_root)
    file_path = (ws / rel).resolve()
    if not str(file_path).startswith(str(ws)):
        raise ValueError("Path traversal outside workspace root")
    if not file_path.exists():
        raise FileNotFoundError(f"File {relative_path} not found in claim workspace")
    return file_path.read_text(encoding="utf-8")


def write_workspace_file(
    claim_id: str,
    relative_path: str,
    content: str,
    expected_hash: str | None = None,
    run_id: str | None = None,
    base_root: str | Path | None = None,
) -> dict[str, str | int]:
    rel = validate_workspace_path(relative_path)
    ws = get_claim_workspace_dir(claim_id, run_id, base_root)
    file_path = (ws / rel).resolve()
    if not str(file_path).startswith(str(ws)):
        raise ValueError("Path traversal outside workspace root")

    if expected_hash and file_path.exists():
        current_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if current_hash != expected_hash:
            raise ValueError(f"Optimistic lock failed for {relative_path}: expected {expected_hash}, got {current_hash}")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_bytes = content.encode("utf-8")
    file_path.write_bytes(file_bytes)
    sha256 = hashlib.sha256(file_bytes).hexdigest()

    return {
        "claim_id": claim_id,
        "relative_path": rel,
        "size_bytes": len(file_bytes),
        "sha256": sha256,
    }
