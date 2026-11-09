"""Artifact publishing and retrieval capabilities."""
from __future__ import annotations

import hashlib
import time
from typing import Any

from app.services.database import default_artifact_repo
from app.services.storage import default_storage


def publish_artifact(
    run_id: str,
    stage: str,
    claim_id: str | None,
    logical_path: str,
    media_type: str,
    content: str | bytes,
    producer_agent_id: str = "orchestrator",
) -> dict[str, Any]:
    # Store immutably in storage service
    storage_res = default_storage.put_immutable(
        tenant_id="default",
        run_id=run_id,
        logical_path=logical_path,
        body=content,
    )

    artifact_id = f"art_{hashlib.md5(f'{run_id}:{logical_path}:{stage}'.encode()).hexdigest()[:12]}"

    manifest_entry = {
        "artifact_id": artifact_id,
        "run_id": run_id,
        "stage": stage,
        "claim_id": claim_id,
        "logical_path": logical_path,
        "version": 1,
        "sha256": storage_res["sha256"],
        "media_type": media_type,
        "size_bytes": storage_res["size_bytes"],
        "producer_agent_id": producer_agent_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "ready",
    }

    default_artifact_repo.add_artifact(manifest_entry)
    return manifest_entry


def read_artifact(artifact_id: str, requester_role: str = "reviewer") -> dict[str, Any]:
    with default_artifact_repo.db.get_connection() as conn:
        row = conn.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if not row:
            raise FileNotFoundError(f"Artifact {artifact_id} not found")
        data = dict(row)

    object_id = f"default/{data['run_id']}/{data['logical_path']}"
    raw_bytes = default_storage.open_readonly(object_id)

    # Return text if text/json, otherwise binary note
    content = None
    if "json" in data["media_type"] or "text" in data["media_type"] or "markdown" in data["media_type"]:
        try:
            content = raw_bytes.decode("utf-8")
        except Exception:
            pass

    data["content"] = content
    return data
