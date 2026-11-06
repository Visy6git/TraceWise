"""Explorer Agent: Performs global exploration and profiling of complete datasets.
Discovers schemas, row counts, candidate primary keys, and relationships,
producing knowledge_graph.json and knowledge_graph.md.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any
from ..base_agent import BaseAgent
from ...agent_tools.source_tools import AgentToolRegistry
from ...services.execution_engine import ExecutionEngine
from ...services.sandbox import AgentSandbox


class ExplorerAgent(BaseAgent):
    def __init__(
        self,
        run_id: str,
        data_engine: ExecutionEngine,
        sandbox: AgentSandbox,
        manifest: list[dict[str, Any]],
        input_dir: Path,
    ):
        super().__init__(
            run_id=run_id,
            agent_id="explorer_agent",
            agent_name="Data Explorer Agent",
            agent_role="Global Dataset & Relationship Profiler",
        )
        self.data_engine = data_engine
        self.sandbox = sandbox
        self.manifest = manifest
        self.input_dir = input_dir
        self.registry = AgentToolRegistry(data_engine, sandbox, manifest)

    def explore(self) -> dict[str, Any]:
        """Runs the complete source data exploration and builds the knowledge graph."""
        self.emit(
            "explorer.file.started",
            "Starting global exploration across all uploaded source datasets.",
            {"source_file_count": sum(1 for m in self.manifest if m.get("role") == "source")},
        )

        source_items = [m for m in self.manifest if m.get("role") == "source"]

        # 1. Ingest all source files into the analytical engine
        for item in source_items:
            stored_name = item["stored_name"]
            orig_name = item["filename"]
            file_path = self.input_dir / stored_name
            if not file_path.exists():
                continue

            self.emit(
                "explorer.file.started",
                f"Ingesting and profiling {orig_name} ({round(item.get('size', 0)/1024, 1)} KB).",
                {"filename": orig_name, "size": item.get("size", 0)},
            )
            try:
                self.data_engine.ingest_source_file(file_path, orig_name)
            except Exception as exc:
                self.emit(
                    "agent_warning",
                    f"Warning during ingestion of {orig_name}: {exc}",
                    {"filename": orig_name, "error": str(exc)},
                )

        # 2. Profile all ingested tables and columns
        tables = self.data_engine.list_tables()
        profiles = {}
        for tbl_meta in tables:
            tbl_name = tbl_meta["table_name"]
            schema = self.data_engine.get_table_schema(tbl_name)
            column_profiles = {}
            candidate_pks = []
            for col_info in schema["columns"]:
                col_name = col_info["name"]
                try:
                    p = self.data_engine.profile_column(tbl_name, col_name)
                    column_profiles[col_name] = p
                    if p["is_candidate_primary_key"]:
                        candidate_pks.append(col_name)
                except Exception:
                    pass

            profiles[tbl_name] = {
                "table_name": tbl_name,
                "filename": tbl_meta["filename"],
                "sheet": tbl_meta["sheet"],
                "total_rows": tbl_meta["row_count"],
                "columns": schema["columns"],
                "candidate_primary_keys": candidate_pks,
                "column_profiles": column_profiles,
            }

            self.emit(
                "explorer.schema.discovered",
                f"Discovered {tbl_meta['sheet']} in {tbl_meta['filename']}: {tbl_meta['row_count']} rows, {len(schema['columns'])} columns.",
                {
                    "table_name": tbl_name,
                    "filename": tbl_meta["filename"],
                    "sheet": tbl_meta["sheet"],
                    "rows": tbl_meta["row_count"],
                    "candidate_pks": candidate_pks,
                },
            )

        # 3. Discover relationships and join cardinality
        relationships = self.data_engine.find_candidate_joins()
        for rel in relationships:
            self.emit(
                "explorer.relationship.discovered",
                f"Discovered candidate relationship between {rel['left_filename']} and {rel['right_filename']} on '{rel['left_original_column']}' ({rel['cardinality']}).",
                rel,
            )

        # 4. Generate Knowledge Graph JSON and Markdown
        kg = {
            "run_id": self.run_id,
            "datasets": [
                {
                    "filename": item["filename"],
                    "stored_name": item["stored_name"],
                    "size": item.get("size", 0),
                    "sha256": item.get("sha256", ""),
                }
                for item in source_items
            ],
            "tables": profiles,
            "relationships": relationships,
        }

        kg_json_str = json.dumps(kg, indent=2, default=str)
        kg_md_str = self._generate_knowledge_graph_markdown(kg)

        # Save to sandbox
        self.sandbox.write_file("knowledge_graph.json", kg_json_str)
        self.sandbox.write_file("knowledge_graph.md", kg_md_str)
        self.sandbox.write_file("relationships.json", json.dumps(relationships, indent=2, default=str))
        self.sandbox.write_file("schema_profiles.json", json.dumps(profiles, indent=2, default=str))

        self.emit(
            "explorer.graph.completed",
            f"Knowledge Graph generated: {len(tables)} tables profiled, {len(relationships)} relationships identified.",
            {
                "tables_count": len(tables),
                "relationships_count": len(relationships),
                "total_records": sum(t["row_count"] for t in tables),
            },
        )

        return kg

    def _generate_knowledge_graph_markdown(self, kg: dict[str, Any]) -> str:
        lines = [
            f"# Pharmacovigilance Knowledge Graph · Run {self.run_id}",
            "",
            "## 1. Source Dataset Inventory",
            "| Filename | Format | Size | SHA-256 |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for ds in kg.get("datasets", []):
            lines.append(f"| `{ds['filename']}` | {Path(ds['filename']).suffix} | {ds['size']} B | `{ds['sha256'][:16]}...` |")

        lines.extend([
            "",
            "## 2. Worksheets & Table Profiles",
            "| Table | Source File | Sheet | Full Rows | Candidate Primary Keys |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for tbl_name, prof in kg.get("tables", {}).items():
            pks = ", ".join(f"`{k}`" for k in prof.get("candidate_primary_keys", [])) or "None"
            lines.append(f"| `{tbl_name}` | `{prof['filename']}` | {prof['sheet']} | {prof['total_rows']:,} | {pks} |")

        lines.extend([
            "",
            "## 3. Discovered Entity Relationships & Join Cardinality",
        ])
        rels = kg.get("relationships", [])
        if not rels:
            lines.append("No common entity identifiers with overlapping values were detected.")
        else:
            lines.extend([
                "| Left Table | Left Key | Right Table | Right Key | Cardinality | Overlapping Keys |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for r in rels:
                lines.append(
                    f"| `{r['left_table']}` | `{r['left_original_column']}` | `{r['right_table']}` | `{r['right_original_column']}` | **{r['cardinality']}** | {r['overlapping_keys']:,} |"
                )

        lines.extend([
            "",
            "## 4. Analytical Recommendations",
            "- Query entire tables deterministically using `execute_readonly_query` without row truncation.",
            "- When joining case-level and event-level exports, verify cardinality to avoid denominator inflation.",
            "- Use exact row provenance indices (`__excel_row__`) to cross-reference reported metrics.",
        ])

        return "\n".join(lines)

