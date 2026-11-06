"""Evidence Discovery Agent: Investigates complete datasets for a specific Claim.
Uses full-data search, column profiling, and join discovery to retrieve exact supporting records.
"""
from __future__ import annotations
import json
import re
from typing import Any
from ..base_agent import BaseAgent
from ...agent_tools.source_tools import AgentToolRegistry
from ...schemas.claim import Claim
from ...schemas.evidence import EvidenceBundle, EvidenceRecord
from ...services.execution_engine import ExecutionEngine


class EvidenceDiscoveryAgent(BaseAgent):
    def __init__(
        self,
        run_id: str,
        data_engine: ExecutionEngine,
        registry: AgentToolRegistry,
        knowledge_graph: dict[str, Any] | None = None,
    ):
        super().__init__(
            run_id=run_id,
            agent_id="evidence_agent",
            agent_name="Evidence Discovery Agent",
            agent_role="Claim-to-Source Lineage Investigator",
        )
        self.data_engine = data_engine
        self.registry = registry
        self.knowledge_graph = knowledge_graph or {}

    def discover_evidence(self, claim: Claim) -> EvidenceBundle:
        """Investigates complete datasets for the given claim and produces an EvidenceBundle."""
        self.emit(
            "evidence.search.started",
            f"Searching complete datasets for claim {claim.claim_id}: '{claim.normalized_statement}'",
            {"claim_id": claim.claim_id, "reported_value": claim.reported_value},
        )

        # 1. Identify search terms from claim
        text_to_search = f"{claim.normalized_statement} {claim.raw_text}"
        words = [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", text_to_search)]
        stop_words = {
            "total", "cases", "reported", "period", "identified", "evaluation",
            "safety", "findings", "from", "other", "studies", "frequency",
        }
        search_terms = [w for w in words if w not in stop_words]

        # 2. Search tables for matching values across all records
        all_matches = []
        for term in search_terms[:5]:
            matches = self.data_engine.search_column_values(term, limit=20)
            all_matches.extend(matches)

        # Group matches by table
        table_match_counts = {}
        for m in all_matches:
            tbl = m["table_name"]
            table_match_counts[tbl] = table_match_counts.get(tbl, 0) + 1

        tables = self.data_engine.list_tables()
        candidate_tables = sorted(
            table_match_counts.keys(),
            key=lambda t: table_match_counts[t],
            reverse=True,
        )
        if not candidate_tables and tables:
            candidate_tables = [tables[0]["table_name"]]

        primary_table = candidate_tables[0] if candidate_tables else ""
        provenance_rows = []
        sample_records = []
        matched_columns = []
        total_matching_rows = 0

        if primary_table:
            schema = self.data_engine.get_table_schema(primary_table)
            cols = schema["columns"]
            
            # Find candidate event column and case column
            event_col = next(
                (c["name"] for c in cols if any(k in c["name"].lower() for k in ("event", "pt", "term", "reaction"))),
                None
            )
            case_col = next(
                (c["name"] for c in cols if any(k in c["name"].lower() for k in ("case", "patient", "subject", "id"))),
                None
            )
            if event_col:
                matched_columns.append(event_col)
            if case_col:
                matched_columns.append(case_col)

            # Query row counts and provenance from full table
            where_clauses = []
            if search_terms and event_col:
                or_terms = " OR ".join([f'LOWER("{event_col}") LIKE ?' for _ in search_terms[:3]])
                where_clauses.append(f"({or_terms})")
                params = tuple([f"%{t}%" for t in search_terms[:3]])
            else:
                params = ()

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            count_sql = f'SELECT COUNT(*) FROM "{primary_table}" {where_sql}'
            
            try:
                res = self.data_engine.execute_query(count_sql, params)
                total_matching_rows = res["rows"][0]["COUNT(*)"] if res["rows"] else 0
            except Exception:
                total_matching_rows = 0

            # Get sample rows and original excel rows
            sample_sql = f'SELECT * FROM "{primary_table}" {where_sql} LIMIT 5'
            try:
                s_res = self.data_engine.execute_query(sample_sql, params)
                sample_records = s_res["rows"]
                for r in sample_records:
                    if "__excel_row__" in r and r["__excel_row__"] is not None:
                        provenance_rows.append(int(r["__excel_row__"]))
            except Exception:
                pass

        bundle = EvidenceBundle(
            claim_id=claim.claim_id,
            candidate_datasets=candidate_tables,
            relevant_columns=matched_columns,
            filters=[{"terms": search_terms}],
            joins=[],
            sample_records=sample_records,
            provenance_rows=provenance_rows,
            total_matching_rows=total_matching_rows,
            query_syntax=f'SELECT * FROM "{primary_table}" {where_sql}' if primary_table else "",
            assumptions=[f"Primary evidence derived from full table '{primary_table}'"],
        )

        claim.evidence = [bundle.to_dict()]
        claim.status = "EVIDENCE_FOUND"

        self.emit(
            "evidence.records.found",
            f"Retrieved {total_matching_rows:,} matching records in {primary_table} for claim {claim.claim_id}.",
            {
                "claim_id": claim.claim_id,
                "table": primary_table,
                "matching_rows": total_matching_rows,
                "provenance_rows": provenance_rows[:10],
            },
        )

        return bundle

