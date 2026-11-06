"""Tool definitions and dispatcher for PV autonomous agents.
Wraps the ExecutionEngine and sandbox into Bedrock Converse-compatible tools.
"""
from __future__ import annotations
from typing import Any
from ..services.execution_engine import ExecutionEngine
from ..services.sandbox import AgentSandbox


class AgentToolRegistry:
    """Central registry providing tool specifications and tool execution for agents."""

    def __init__(self, data_engine: ExecutionEngine, sandbox: AgentSandbox, manifest: list[dict[str, Any]]):
        self.data_engine = data_engine
        self.sandbox = sandbox
        self.manifest = manifest

    def get_tool_specs(self) -> list[dict[str, Any]]:
        """Returns Bedrock Converse-compatible tool specs."""
        return [
            {
                "name": "list_source_files",
                "description": "Inventories all source spreadsheets, line listings, and documents available to this run.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {},
                    }
                },
            },
            {
                "name": "get_dataset_manifest",
                "description": "Retrieves metadata and full worksheet inventory from all ingested datasets.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {},
                    }
                },
            },
            {
                "name": "get_sheet_schema",
                "description": "Retrieves column names, original names, and row counts for a specific table/sheet.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string", "description": "Name of the table"}
                        },
                        "required": ["table_name"],
                    }
                },
            },
            {
                "name": "profile_column",
                "description": "Calculates distinct values, null rates, candidate primary key status, and top value distribution for a column.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string", "description": "Target table name"},
                            "column_name": {"type": "string", "description": "Target column name"}
                        },
                        "required": ["table_name", "column_name"],
                    }
                },
            },
            {
                "name": "search_column_values",
                "description": "Searches for candidate terminology (e.g. adverse event terms, drugs, case numbers) across complete datasets.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "search_term": {"type": "string", "description": "Term or substring to search for"},
                            "table_name": {"type": "string", "description": "Optional table name to restrict search"},
                            "column_name": {"type": "string", "description": "Optional column name to restrict search"},
                            "limit": {"type": "integer", "description": "Max matching rows (default 30)"}
                        },
                        "required": ["search_term"],
                    }
                },
            },
            {
                "name": "sample_rows",
                "description": "Inspects representative sample records from a table with optional filter condition.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string", "description": "Target table name"},
                            "limit": {"type": "integer", "description": "Number of sample rows to fetch"},
                            "where_clause": {"type": "string", "description": "Optional SQL WHERE condition"}
                        },
                        "required": ["table_name"],
                    }
                },
            },
            {
                "name": "find_candidate_joins",
                "description": "Analyzes relationships and discovers candidate key connections across all datasets.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {},
                    }
                },
            },
            {
                "name": "test_join_cardinality",
                "description": "Tests join cardinality (1:1, 1:N, N:N), key uniqueness, and row multiplication factor between two datasets.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "left_table": {"type": "string", "description": "Left table name"},
                            "right_table": {"type": "string", "description": "Right table name"},
                            "left_key": {"type": "string", "description": "Left table key column"},
                            "right_key": {"type": "string", "description": "Right table key column"}
                        },
                        "required": ["left_table", "right_table", "left_key", "right_key"],
                    }
                },
            },
            {
                "name": "execute_readonly_query",
                "description": "Executes a complete-data analytical SQL query (SELECT only) to calculate metrics, distinct counts, or groupings.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string", "description": "Read-only SQL query"}
                        },
                        "required": ["sql"],
                    }
                },
            },
            {
                "name": "get_row_provenance",
                "description": "Returns original Excel row numbers and file coordinates for records matching a specific query.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string", "description": "Target table"},
                            "where_clause": {"type": "string", "description": "SQL condition matching the records"}
                        },
                        "required": ["table_name"],
                    }
                },
            },
            {
                "name": "execute_sandbox_python",
                "description": "Executes an advanced Python script in the isolated sandbox if a metric cannot be expressed via SQL.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "script_name": {"type": "string", "description": "Filename of python script (e.g. calc.py)"},
                            "script_code": {"type": "string", "description": "Python code to execute"}
                        },
                        "required": ["script_name", "script_code"],
                    }
                },
            },
        ]

    def execute_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Executes a registered tool by name with arguments."""
        if name == "list_source_files":
            return [
                {
                    "filename": item["filename"],
                    "stored_name": item["stored_name"],
                    "role": item.get("role", "source"),
                    "size": item.get("size", 0),
                }
                for item in self.manifest
                if item.get("role") == "source"
            ]

        if name == "get_dataset_manifest":
            return self.data_engine.list_tables()

        if name == "get_sheet_schema":
            return self.data_engine.get_table_schema(args["table_name"])

        if name == "profile_column":
            return self.data_engine.profile_column(args["table_name"], args["column_name"])

        if name == "search_column_values":
            return self.data_engine.search_column_values(
                search_term=args["search_term"],
                table_name=args.get("table_name"),
                column_name=args.get("column_name"),
                limit=args.get("limit", 30),
            )

        if name == "sample_rows":
            return self.data_engine.sample_rows(
                table_name=args["table_name"],
                limit=args.get("limit", 5),
                where_clause=args.get("where_clause"),
            )

        if name == "find_candidate_joins":
            return self.data_engine.find_candidate_joins()

        if name == "test_join_cardinality":
            return self.data_engine.test_join_cardinality(
                left_table=args["left_table"],
                right_table=args["right_table"],
                left_key=args["left_key"],
                right_key=args["right_key"],
            )

        if name == "execute_readonly_query":
            return self.data_engine.execute_query(args["sql"])

        if name == "get_row_provenance":
            tbl = args["table_name"]
            cond = args.get("where_clause", "1=1")
            sql = f'SELECT "__source_file__", "__sheet_name__", "__excel_row__" FROM "{tbl}" WHERE {cond} LIMIT 50'
            res = self.data_engine.execute_query(sql)
            return res.get("rows", [])

        if name == "execute_sandbox_python":
            self.sandbox.write_file(args["script_name"], args["script_code"])
            res = self.sandbox.execute_python(args["script_name"])
            return res.to_dict()

        raise ValueError(f"Unknown agent tool: '{name}'")

