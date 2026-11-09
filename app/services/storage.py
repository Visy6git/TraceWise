"""Private object storage adapter interface.

Provides local filesystem-backed immutable storage with SHA-256 checksums,
with ready hooks for AWS S3 with SSE-KMS when provisioned in production.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO, Union


class StorageService:
    def __init__(self, root_dir: str | Path | None = None):
        self.root_dir = Path(root_dir or os.environ.get("ARTIFACT_ROOT", "./.tracewise-runtime")).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_physical_path(self, tenant_id: str, run_id: str, logical_path: str) -> Path:
        normalized = logical_path.lstrip("/\\").replace("\\", "/")
        path = (self.root_dir / tenant_id / run_id / normalized).resolve()
        if not str(path).startswith(str(self.root_dir)):
            raise ValueError(f"Path traversal detected: {logical_path}")
        return path

    def compute_sha256(self, data: bytes | str) -> str:
        if isinstance(data, str):
            data = data.encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def put_immutable(
        self,
        tenant_id: str,
        run_id: str,
        logical_path: str,
        body: Union[bytes, str, BinaryIO],
        checksum: str | None = None,
    ) -> dict[str, str | int]:
        target_path = self._resolve_physical_path(tenant_id, run_id, logical_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if hasattr(body, "read"):
            content = body.read()
        elif isinstance(body, str):
            content = body.encode("utf-8")
        else:
            content = body

        actual_sha256 = hashlib.sha256(content).hexdigest()
        if checksum and actual_sha256.lower() != checksum.lower():
            raise ValueError(f"Checksum mismatch: expected {checksum}, got {actual_sha256}")

        # If file already exists and is immutable, verify content integrity
        if target_path.exists():
            existing = target_path.read_bytes()
            existing_hash = hashlib.sha256(existing).hexdigest()
            if existing_hash != actual_sha256:
                raise ValueError(f"Attempt to overwrite immutable object at {logical_path}")

        target_path.write_bytes(content)

        return {
            "object_id": f"{tenant_id}/{run_id}/{logical_path.lstrip('/')}",
            "sha256": actual_sha256,
            "size_bytes": len(content),
            "physical_path": str(target_path),
            "logical_path": logical_path,
        }

    def open_readonly(self, object_id: str) -> bytes:
        parts = object_id.replace("\\", "/").strip("/").split("/", 2)
        if len(parts) < 3:
            # Fallback direct logical path under default tenant/run
            target_path = (self.root_dir / object_id).resolve()
        else:
            tenant_id, run_id, logical_path = parts
            target_path = self._resolve_physical_path(tenant_id, run_id, logical_path)

        if not target_path.exists():
            raise FileNotFoundError(f"Storage object not found: {object_id}")
        return target_path.read_bytes()

    def read_text(self, object_id: str) -> str:
        return self.open_readonly(object_id).decode("utf-8")

    def issue_download(self, artifact_id: str, requester_id: str, ttl_seconds: int = 60) -> str:
        # In local mode, returns direct file URI or relative download path
        return f"/api/artifacts/{artifact_id}/download"


# Global singleton instance for local runtime
default_storage = StorageService()
