"""Headless-safe safety approval policy confining writes strictly to workspace cwd."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from app.harness.config import ApprovalPolicy
from app.harness.paths import is_within_dir, strip_extended_prefix


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass
class ApprovalContext:
    tool_name: str
    params: dict[str, Any]
    is_mutating: bool
    affected_paths: list[Path]
    command: str | None = None
    is_dangerous: bool = False


class ApprovalManager:
    """Enforce workspace write boundaries cleanly for autonomous headless harness runs."""

    def __init__(self, approval_policy: ApprovalPolicy, cwd: Path, readonly_dirs: list[Path] | None = None):
        self.approval_policy = approval_policy
        self.cwd = strip_extended_prefix(cwd).resolve()
        self.readonly_dirs = [strip_extended_prefix(p).resolve() for p in (readonly_dirs or [])]

    async def check_approval(self, context: ApprovalContext) -> ApprovalDecision:
        if context.is_dangerous:
            return ApprovalDecision.REJECTED

        if context.is_mutating:
            for path in context.affected_paths:
                resolved = strip_extended_prefix(path).resolve()
                if not is_within_dir(resolved, self.cwd):
                    return ApprovalDecision.REJECTED
                # Even if readonly_dir is nested inside cwd somehow, reject writes into readonly_dirs
                if any(is_within_dir(resolved, ro) for ro in self.readonly_dirs):
                    return ApprovalDecision.REJECTED

        if self.approval_policy in {
            ApprovalPolicy.AUTO,
            ApprovalPolicy.YOLO,
            ApprovalPolicy.AUTO_EDIT,
            ApprovalPolicy.ON_REQUEST,
            ApprovalPolicy.ON_FAILURE,
        }:
            return ApprovalDecision.APPROVED

        return ApprovalDecision.REJECTED if context.is_mutating else ApprovalDecision.APPROVED

    def request_confirmation(self, confirmation: Any) -> bool:
        return False

