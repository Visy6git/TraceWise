"""Rule Engineer Agent: Constructs declarative MetricRule specifications and executes them deterministically.
Compiles rules into SQL queries executed against the analytical engine.
"""
from __future__ import annotations
import json
import re
from typing import Any
from ..base_agent import BaseAgent
from ...schemas.claim import Claim
from ...schemas.evidence import EvidenceBundle
from ...schemas.metric_rule import MetricRule, MetricResult, MetricFilter
from ...services.execution_engine import ExecutionEngine
from ...services.sandbox import AgentSandbox


class RuleEngineerAgent(BaseAgent):
    def __init__(
        self,
        run_id: str,
        data_engine: ExecutionEngine,
        sandbox: AgentSandbox,
    ):
        super().__init__(
            run_id=run_id,
            agent_id="rule_engineer_agent",
            agent_name="Rule Engineer Agent",
            agent_role="Deterministic Metric & Lineage Rule Builder",
        )
        self.data_engine = data_engine
        self.sandbox = sandbox

    def formulate_and_execute_rule(self, claim: Claim, evidence: EvidenceBundle) -> tuple[MetricRule, MetricResult]:
        """Formulates a MetricRule from evidence, compiles it, and executes it against the database."""
        self.emit(
            "rules.draft.created",
            f"Drafting deterministic calculation rule for claim {claim.claim_id}",
            {"claim_id": claim.claim_id, "statement": claim.normalized_statement},
        )

        primary_table = evidence.candidate_datasets[0] if evidence.candidate_datasets else ""
        if not primary_table:
            tables = self.data_engine.list_tables()
            primary_table = tables[0]["table_name"] if tables else ""

        schema = self.data_engine.get_table_schema(primary_table) if primary_table else {"columns": []}
        cols = schema["columns"]

        case_col = next(
            (c["name"] for c in cols if any(k in c["name"].lower() for k in ("case", "patient", "subject", "id"))),
            cols[0]["name"] if cols else "id"
        )
        event_col = next(
            (c["name"] for c in cols if any(k in c["name"].lower() for k in ("event", "pt", "term", "reaction"))),
            None
        )
        source_col = next(
            (c["name"] for c in cols if any(k in c["name"].lower() for k in ("source", "study", "type", "report_type"))),
            None
        )

        filters: list[MetricFilter] = []

        # 1. Add event term filter if applicable
        if event_col:
            # Extract keywords from normalized statement or title
            clean_terms = [
                t.lower() for t in re.findall(r"[a-zA-Z]{4,}", claim.normalized_statement)
                if t.lower() not in {"total", "cases", "reported", "period", "identified", "evaluation", "safety", "findings", "frequency"}
            ]
            if clean_terms:
                filters.append(MetricFilter(column=event_col, operator="contains", value=clean_terms[0]))

        # 2. Add source split filter if applicable
        if source_col and claim.claim_type == "source_split":
            if "spontaneous" in claim.normalized_statement.lower():
                filters.append(MetricFilter(column=source_col, operator="contains", value="Spontaneous"))
            elif "clinical" in claim.normalized_statement.lower() or "study" in claim.normalized_statement.lower():
                filters.append(MetricFilter(column=source_col, operator="contains", value="Study"))

        rule = MetricRule(
            rule_id=f"RULE-{claim.claim_id}",
            claim_id=claim.claim_id,
            version=1,
            name=f"Calculation for {claim.normalized_statement}",
            source_table=primary_table,
            entity_identifier=case_col,
            aggregation="distinct_count",
            filters=filters,
            output_unit=claim.unit or "cases",
            assumptions=[
                f"Aggregating distinct '{case_col}' from table '{primary_table}'",
                "Applied exact and case-insensitive string containment on event terminology",
            ],
            status="drafted",
        )

        self.emit(
            "rules.execution.started",
            f"Compiling and executing rule {rule.rule_id} for claim {claim.claim_id}",
            {"rule_id": rule.rule_id, "table": primary_table, "aggregation": rule.aggregation},
        )

        # Execute deterministic compilation
        result = self.data_engine.compile_and_execute_rule(rule)
        rule.status = "executed" if result.status == "success" else "rejected"

        claim.rule = rule.to_dict()
        claim.calculation_result = result.to_dict()
        claim.status = "RULE_EXECUTED"

        self.emit(
            "rules.execution.completed",
            f"Rule {rule.rule_id} computed value: {result.computed_value} ({result.execution_ms} ms)",
            {
                "rule_id": rule.rule_id,
                "computed_value": result.computed_value,
                "numeric_value": result.numeric_value,
                "distinct_entities": result.distinct_entities,
                "execution_ms": result.execution_ms,
                "executed_sql": result.executed_sql,
            },
        )

        return rule, result

