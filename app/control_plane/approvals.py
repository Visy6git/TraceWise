"""Approval invariants. Identity, signatures and persistence remain deployment TODOs."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalRequest:
    reviewer_id: str
    decision: str
    expected_version: int
    expected_manifest_hash: str
    current_version: int
    current_manifest_hash: str
    reviewer_role: str


def validate_approval(request: ApprovalRequest) -> None:
    """Validate stale-view and role constraints before a durable approval is recorded."""
    if request.reviewer_role not in {"reviewer", "admin", "pv_approver"}:
        raise PermissionError("Reviewer role is required")
    if request.decision not in {"approve", "request_changes"}:
        raise ValueError("Decision must be approve or request_changes")
    if request.expected_version != request.current_version:
        raise ValueError("Stale review: artifact version changed; refresh before deciding")
    if request.expected_manifest_hash != request.current_manifest_hash:
        raise ValueError("Stale review: artifact manifest hash changed; refresh before deciding")
    if not request.reviewer_id.strip():
        raise ValueError("Authenticated reviewer identity is required")
