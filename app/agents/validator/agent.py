"""Validator Agent: Performs independent verification of claims, evidence, and calculations.
Controls the 3-attempt bounded retry loop with targeted feedback.
"""
from __future__ import annotations
import json
from typing import Any
from ..base_agent import BaseAgent
from ...schemas.claim import Claim
from ...schemas.evidence import EvidenceBundle
from ...schemas.metric_rule import MetricRule, MetricResult
from ...schemas.validation import ValidationCheck, ValidationResult
from ...services.execution_engine import ExecutionEngine


class ValidatorAgent(BaseAgent):
    def __init__(self, run_id: str, data_engine: ExecutionEngine):
        super().__init__(
            run_id=run_id,
            agent_id="validator_agent",
            agent_name="Independent Validator Agent",
            agent_role="Lineage, Calculation & Reconciliation Auditor",
        )
        self.data_engine = data_engine

    def validate_claim(
        self,
        claim: Claim,
        evidence: EvidenceBundle,
        rule: MetricRule,
        result: MetricResult,
        attempt: int = 1,
    ) -> ValidationResult:
        """Independently evaluates the claim, retrieved evidence, rule logic, and reconciliation."""
        checks: list[ValidationCheck] = []
        target_stage: str | None = None
        feedback: str | None = None

        # 1. Check claim integrity
        claim_ok = bool(claim.raw_text and claim.normalized_statement)
        checks.append(ValidationCheck(
            name="claim_extraction_integrity",
            passed=claim_ok,
            details=f"Statement extracted: '{claim.normalized_statement}'",
        ))

        # 2. Check evidence support
        evidence_ok = bool(evidence.candidate_datasets and evidence.total_matching_rows > 0)
        checks.append(ValidationCheck(
            name="evidence_support",
            passed=evidence_ok,
            details=f"Found {evidence.total_matching_rows} records in {evidence.candidate_datasets}",
        ))
        if not evidence_ok and not target_stage:
            target_stage = "evidence"
            feedback = "No matching records found in candidate datasets; explore alternative event terminology or datasets."

        # 3. Check rule execution determinism
        rule_ok = (result.status == "success" and result.numeric_value is not None)
        checks.append(ValidationCheck(
            name="rule_execution_success",
            passed=rule_ok,
            details=f"Rule executed with exit status {result.status} ({result.execution_ms} ms)",
        ))
        if not rule_ok and not target_stage:
            target_stage = "rule_engineer"
            feedback = f"Rule compilation or execution failed: {result.error_message}"

        # 4. Check reconciliation against reported reference figure
        reconciled = True
        discrepancy = None
        if claim.numeric_value is not None and result.numeric_value is not None:
            diff = abs(claim.numeric_value - result.numeric_value)
            reconciled = (diff == 0)
            if not reconciled:
                discrepancy = f"Reported figure is {claim.numeric_value}, but calculated result is {result.numeric_value} (difference: {diff})."
                checks.append(ValidationCheck(
                    name="reconciliation",
                    passed=False,
                    details=discrepancy,
                    severity="error",
                ))
                if not target_stage:
                    target_stage = "rule_engineer"
                    feedback = f"Calculation discrepancy: reported {claim.numeric_value} vs calculated {result.numeric_value}. Refine filters or population criteria."
            else:
                checks.append(ValidationCheck(
                    name="reconciliation",
                    passed=True,
                    details=f"Exact match: reported {claim.numeric_value} == calculated {result.numeric_value}",
                ))
        else:
            checks.append(ValidationCheck(
                name="reconciliation",
                passed=True,
                details="Narrative or unquantified claim; qualitative evidence matched.",
                severity="info",
            ))

        all_passed = all(c.passed for c in checks if c.severity == "error")

        if all_passed:
            status = "VALIDATED"
        elif attempt >= 3:
            status = "UNRESOLVED"
            feedback = f"Maximum of 3 validation attempts reached without complete reconciliation. Flagged for human review. {discrepancy or ''}"
        else:
            status = "RETRY_NEEDED"

        val_res = ValidationResult(
            claim_id=claim.claim_id,
            attempt=attempt,
            status=status,
            checks=checks,
            reconciled=reconciled,
            discrepancy=discrepancy,
            target_stage_for_retry=target_stage,
            feedback_message=feedback,
            audit_trail=f"Attempt {attempt}: {'PASSED' if all_passed else 'RETRY_NEEDED' if status == 'RETRY_NEEDED' else 'UNRESOLVED'}",
        )

        claim.validation = val_res.to_dict()
        claim.status = status

        self.emit(
            "validator.check.completed",
            f"Validation attempt {attempt} for {claim.claim_id}: {status} ({len([c for c in checks if c.passed])}/{len(checks)} checks passed)",
            {
                "claim_id": claim.claim_id,
                "status": status,
                "attempt": attempt,
                "reconciled": reconciled,
                "discrepancy": discrepancy,
            },
        )

        if status == "RETRY_NEEDED":
            self.emit(
                "validator.retry.requested",
                f"Validation requested retry #{attempt+1} targeting '{target_stage}': {feedback}",
                {
                    "claim_id": claim.claim_id,
                    "target_stage": target_stage,
                    "attempt": attempt,
                    "feedback": feedback,
                },
            )

        return val_res

