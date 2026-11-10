"""Control plane tests: state transitions, approval invariants, message ACL, invalidation."""
from __future__ import annotations

import pytest

from app.control_plane.approvals import ApprovalRequest, validate_approval
from app.control_plane.dependency_invalidator import descendants, invalidation_plan
from app.control_plane.message_acl import AgentIdentity, MessageDenied, authorize_message
from app.control_plane.run_state import (
    InvalidTransition,
    RunState,
    validate_stage_start,
    validate_transition,
)


def test_rules_stage_requires_claims_approval():
    with pytest.raises(InvalidTransition):
        validate_stage_start(RunState.CLAIMS_AWAITING_REVIEW, "rules")
    validate_stage_start(RunState.CLAIMS_APPROVED, "rules")


def test_evaluator_stage_requires_rules_approval():
    with pytest.raises(InvalidTransition):
        validate_stage_start(RunState.CLAIMS_APPROVED, "evaluation")
    validate_stage_start(RunState.RULES_APPROVED, "evaluation")


def test_invalid_transition_rejected():
    with pytest.raises(InvalidTransition):
        validate_transition(RunState.COMPLETE, RunState.CLAIMS_RUNNING)


def test_approval_rejects_stale_manifest():
    request = ApprovalRequest(
        "reviewer-1",
        "approve",
        2,
        "hash-old-0000000000",
        3,
        "hash-new-0000000000",
        "reviewer",
    )
    with pytest.raises(ValueError, match="Stale review"):
        validate_approval(request)


def test_claims_and_rules_exchange_only_via_control_plane():
    claims = AgentIdentity("claims-main", "claims", "orchestrator")
    rules = AgentIdentity("rules-main", "rules", "orchestrator")
    with pytest.raises(MessageDenied):
        authorize_message(claims, rules, via_control_plane=False, artifact_refs=[])
    authorize_message(
        claims,
        rules,
        via_control_plane=True,
        artifact_refs=["artifact://stage1/manifest-v1"],
    )


def test_dependency_invalidation_transitive():
    edges = [
        ("claim-1", "evidence-1"),
        ("evidence-1", "rule-1"),
        ("rule-1", "eval-1"),
        ("claim-2", "rule-2"),
    ]
    assert descendants({"claim-1"}, edges) == {"evidence-1", "rule-1", "eval-1"}
    assert invalidation_plan({"claim-1"}, edges)["dependent_artifacts_to_supersede"] == [
        "eval-1",
        "evidence-1",
        "rule-1",
    ]


def test_rework_requires_explicit_reopened_stage():
    with pytest.raises(InvalidTransition):
        validate_stage_start(RunState.CHANGES_REQUESTED, "rules")
    validate_stage_start(RunState.CHANGES_REQUESTED, "rules", rework_stage="rules")
    with pytest.raises(InvalidTransition):
        validate_stage_start(RunState.CHANGES_REQUESTED, "claims", rework_stage="rules")

