"""Analytical Execution and Data Engine for TraceWise.
Provides high-performance, full-dataset querying, profiling, join analysis,
and deterministic rule compilation using SQLite and optional DuckDB.
"""
from __future__ import annotations
import csv
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from ..schemas.metric_rule import MetricRule, MetricResult, MetricFilter, MetricJoin


class ExecutionEngine:
    """Analytical data engine that stores complete datasets for a run in an isolated database."""

    def __init__(self, run_dir: Path, db_path: Path | None = None):
        self.run_dir = run_dir
        self.db_path = db_path or (run_dir / "analytics.sqlite")
        self._local = threading.local()
        self.table_metadata: dict[str, dict[str, Any]] = {}
        self.column_name_map: dict[str, dict[str, str]] = {}  # table -> {sanitized: original}

    @property
    def conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def close(self):
        try:
            if hasattr(self._local, "conn") and self._local.conn:
                self._local.conn.close()
                self._local.conn = None
        except Exception:
            pass

    @staticmethod
    def sanitize_identifier(name: str) -> str:
        s = re.sub(r"[^a-zA-Z0-9_]+", "_", str(name).strip().lower()).strip("_")
        if not s or s[0].isdigit():
            s = f"col_{s}"
        return s

    def ingest_source_file(self, file_path: Path, original_filename: str):
        """Ingests all worksheets or records from a source file into SQL tables."""
        ext = file_path.suffix.lower()
        if ext in {".xlsx", ".xlsm", ".xltx", ".xls"}:
            self._ingest_excel(file_path, original_filename)
        elif ext == ".csv":
            self._ingest_csv(file_path, original_filename)

    def _ingest_csv(self, file_path: Path, original_filename: str):
        table_base = self.sanitize_identifier(file_path.stem)
        table_name = f"tbl_{table_base}"
        
        with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return
            
            sanitized_cols = []
            col_map = {}
            seen = set()
            for i, col in enumerate(header):
                san = self.sanitize_identifier(col) or f"col_{i+1}"
                orig_san = san
                c = 1
                while san in seen:
                    san = f"{orig_san}_{c}"
                    c += 1
                seen.add(san)
                sanitized_cols.append(san)
                col_map[san] = col

            col_defs = [f'"{col}" TEXT' for col in sanitized_cols]
            col_defs.append('"__source_file__" TEXT')
            col_defs.append('"__excel_row__" INTEGER')

            cur = self.conn.cursor()
            cur.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            cur.execute(f'CREATE TABLE "{table_name}" ({", ".join(col_defs)})')

            placeholders = ", ".join(["?"] * (len(sanitized_cols) + 2))
            insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders})'

            rows_to_insert = []
            for row_idx, row in enumerate(reader, start=2):
                padded = [row[i] if i < len(row) else None for i in range(len(sanitized_cols))]
                padded.append(original_filename)
                padded.append(row_idx)
                rows_to_insert.append(padded)
                if len(rows_to_insert) >= 5000:
                    cur.executemany(insert_sql, rows_to_insert)
                    rows_to_insert = []

            if rows_to_insert:
                cur.executemany(insert_sql, rows_to_insert)

            self.conn.commit()
            
            cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            row_count = cur.fetchone()[0]

            self.table_metadata[table_name] = {
                "table_name": table_name,
                "filename": original_filename,
                "sheet": "CSV",
                "columns": sanitized_cols,
                "row_count": row_count,
            }
            self.column_name_map[table_name] = col_map

    def _ingest_excel(self, file_path: Path, original_filename: str):
        wb = load_workbook(file_path, read_only=True, data_only=True)
        file_stem = self.sanitize_identifier(file_path.stem)

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            sheet_stem = self.sanitize_identifier(sheet_name)
            table_name = f"tbl_{file_stem}_{sheet_stem}"[:60].rstrip("_")

            # Scan first 60 rows for candidate headers
            scan = list(ws.iter_rows(min_row=1, max_row=min(ws.max_row or 1, 60), values_only=True))
            header_idx = None
            for i, row in enumerate(scan):
                values = [str(v).strip() for v in row if v is not None]
                if any(v.casefold() in {"case number", "case id", "patient id", "event pt", "event pt (primary path)"} for v in values):
                    header_idx = i
                    break
            if header_idx is None:
                header_idx = next(
                    (i for i, row in enumerate(scan) if sum(bool(v is not None and str(v).strip()) for v in row) >= 2),
                    None
                )
            if header_idx is None:
                continue

            raw_header = scan[header_idx]
            sanitized_cols = []
            col_map = {}
            seen = set()
            for i, val in enumerate(raw_header):
                orig_name = str(val).strip() if val is not None else f"Column_{i+1}"
                san = self.sanitize_identifier(orig_name) or f"col_{i+1}"
                orig_san = san
                c = 1
                while san in seen:
                    san = f"{orig_san}_{c}"
                    c += 1
                seen.add(san)
                sanitized_cols.append(san)
                col_map[san] = orig_name

            col_defs = [f'"{col}" TEXT' for col in sanitized_cols]
            col_defs.append('"__source_file__" TEXT')
            col_defs.append('"__sheet_name__" TEXT')
            col_defs.append('"__excel_row__" INTEGER')

            cur = self.conn.cursor()
            cur.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            cur.execute(f'CREATE TABLE "{table_name}" ({", ".join(col_defs)})')

            placeholders = ", ".join(["?"] * (len(sanitized_cols) + 3))
            insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders})'

            rows_to_insert = []
            for excel_row, row in enumerate(ws.iter_rows(min_row=header_idx + 2, max_col=len(sanitized_cols), values_only=True), header_idx + 2):
                if not row or not any(v is not None and str(v).strip() for v in row):
                    continue
                vals = [str(row[j]).strip() if j < len(row) and row[j] is not None else "" for j in range(len(sanitized_cols))]
                vals.append(original_filename)
                vals.append(sheet_name)
                vals.append(excel_row)
                rows_to_insert.append(vals)
                if len(rows_to_insert) >= 5000:
                    cur.executemany(insert_sql, rows_to_insert)
                    rows_to_insert = []

            if rows_to_insert:
                cur.executemany(insert_sql, rows_to_insert)

            self.conn.commit()

            cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            row_count = cur.fetchone()[0]

            self.table_metadata[table_name] = {
                "table_name": table_name,
                "filename": original_filename,
                "sheet": sheet_name,
                "columns": sanitized_cols,
                "row_count": row_count,
            }
            self.column_name_map[table_name] = col_map

        wb.close()

    def list_tables(self) -> list[dict[str, Any]]:
        return list(self.table_metadata.values())

    def get_table_schema(self, table_name: str) -> dict[str, Any]:
        if table_name not in self.table_metadata:
            raise ValueError(f"Table '{table_name}' does not exist in analytical engine.")
        meta = self.table_metadata[table_name]
        cols = meta["columns"]
        col_map = self.column_name_map.get(table_name, {})
        return {
            "table_name": table_name,
            "filename": meta["filename"],
            "sheet": meta["sheet"],
            "row_count": meta["row_count"],
            "columns": [
                {
                    "name": col,
                    "original_name": col_map.get(col, col),
                }
                for col in cols
            ],
        }

    def profile_column(self, table_name: str, column_name: str) -> dict[str, Any]:
        if table_name not in self.table_metadata:
            raise ValueError(f"Table '{table_name}' not found.")
        cur = self.conn.cursor()
        total = self.table_metadata[table_name]["row_count"]
        cur.execute(f'SELECT COUNT(DISTINCT "{column_name}") FROM "{table_name}" WHERE "{column_name}" IS NOT NULL AND "{column_name}" != ""')
        distinct_count = cur.fetchone()[0]

        cur.execute(f'SELECT COUNT(*) FROM "{table_name}" WHERE "{column_name}" IS NULL OR "{column_name}" = ""')
        null_count = cur.fetchone()[0]

        cur.execute(f'''
            SELECT "{column_name}", COUNT(*) as cnt
            FROM "{table_name}"
            WHERE "{column_name}" IS NOT NULL AND "{column_name}" != ""
            GROUP BY "{column_name}"
            ORDER BY cnt DESC
            LIMIT 10
        ''')
        top_values = [{"value": row[0], "count": row[1]} for row in cur.fetchall()]

        is_candidate_pk = (distinct_count == total and total > 0 and null_count == 0)

        return {
            "table_name": table_name,
            "column_name": column_name,
            "original_name": self.column_name_map.get(table_name, {}).get(column_name, column_name),
            "total_rows": total,
            "distinct_count": distinct_count,
            "null_count": null_count,
            "null_percentage": round((null_count / total * 100), 2) if total else 0.0,
            "is_candidate_primary_key": is_candidate_pk,
            "top_values": top_values,
        }

    def search_column_values(self, search_term: str, table_name: str | None = None, column_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Searches across tables/columns for records matching the search term."""
        cur = self.conn.cursor()
        results = []
        target_tables = [table_name] if table_name else list(self.table_metadata.keys())

        for tbl in target_tables:
            if tbl not in self.table_metadata:
                continue
            cols = [column_name] if column_name else self.table_metadata[tbl]["columns"]
            for col in cols:
                query = f'''
                    SELECT "{col}", "__excel_row__", "__source_file__"
                    FROM "{tbl}"
                    WHERE LOWER("{col}") LIKE ?
                    LIMIT ?
                '''
                cur.execute(query, (f"%{search_term.lower()}%", limit - len(results)))
                for row in cur.fetchall():
                    results.append({
                        "table_name": tbl,
                        "filename": row["__source_file__"],
                        "column": col,
                        "original_column": self.column_name_map.get(tbl, {}).get(col, col),
                        "matched_value": row[col],
                        "excel_row": row["__excel_row__"],
                    })
                    if len(results) >= limit:
                        return results
        return results

    def sample_rows(self, table_name: str, limit: int = 5, where_clause: str | None = None) -> list[dict[str, Any]]:
        if table_name not in self.table_metadata:
            raise ValueError(f"Table '{table_name}' not found.")
        cur = self.conn.cursor()
        sql = f'SELECT * FROM "{table_name}"'
        if where_clause:
            sql += f' WHERE {where_clause}'
        sql += f' LIMIT {int(limit)}'
        cur.execute(sql)
        rows = cur.fetchall()
        col_map = self.column_name_map.get(table_name, {})
        return [
            {col_map.get(k, k): v for k, v in dict(row).items()}
            for row in rows
        ]

    def find_candidate_joins(self) -> list[dict[str, Any]]:
        """Discovers candidate keys and joins between tables based on shared column names and value overlaps."""
        tables = list(self.table_metadata.keys())
        candidate_joins = []
        cur = self.conn.cursor()

        for i in range(len(tables)):
            for j in range(i + 1, len(tables)):
                t1, t2 = tables[i], tables[j]
                cols1 = self.table_metadata[t1]["columns"]
                cols2 = self.table_metadata[t2]["columns"]

                for c1 in cols1:
                    orig1 = self.column_name_map[t1].get(c1, c1).casefold()
                    if not any(k in orig1 for k in ("case", "patient", "subject", "id", "study")):
                        continue

                    for c2 in cols2:
                        orig2 = self.column_name_map[t2].get(c2, c2).casefold()
                        if orig1 == orig2 or (("case" in orig1 and "case" in orig2) and ("num" in orig1 or "id" in orig1) and ("num" in orig2 or "id" in orig2)):
                            # Test overlap
                            cur.execute(f'''
                                SELECT COUNT(DISTINCT t1."{c1}")
                                FROM "{t1}" t1
                                INNER JOIN "{t2}" t2 ON t1."{c1}" = t2."{c2}"
                                WHERE t1."{c1}" IS NOT NULL AND t1."{c1}" != ""
                            ''')
                            overlap_count = cur.fetchone()[0]
                            if overlap_count > 0:
                                card = self.test_join_cardinality(t1, t2, c1, c2)
                                candidate_joins.append({
                                    "left_table": t1,
                                    "left_filename": self.table_metadata[t1]["filename"],
                                    "left_column": c1,
                                    "left_original_column": self.column_name_map[t1].get(c1, c1),
                                    "right_table": t2,
                                    "right_filename": self.table_metadata[t2]["filename"],
                                    "right_column": c2,
                                    "right_original_column": self.column_name_map[t2].get(c2, c2),
                                    "overlapping_keys": overlap_count,
                                    "cardinality": card["cardinality"],
                                    "left_distinct": card["left_distinct_keys"],
                                    "right_distinct": card["right_distinct_keys"],
                                })
        return candidate_joins

    def test_join_cardinality(self, left_table: str, right_table: str, left_key: str, right_key: str) -> dict[str, Any]:
        """Analyzes join cardinality between two tables to detect 1:1, 1:N, or N:N relationship."""
        cur = self.conn.cursor()
        cur.execute(f'SELECT COUNT(DISTINCT "{left_key}") FROM "{left_table}" WHERE "{left_key}" IS NOT NULL')
        left_distinct = cur.fetchone()[0]
        cur.execute(f'SELECT COUNT(*) FROM "{left_table}" WHERE "{left_key}" IS NOT NULL')
        left_rows = cur.fetchone()[0]

        cur.execute(f'SELECT COUNT(DISTINCT "{right_key}") FROM "{right_table}" WHERE "{right_key}" IS NOT NULL')
        right_distinct = cur.fetchone()[0]
        cur.execute(f'SELECT COUNT(*) FROM "{right_table}" WHERE "{right_key}" IS NOT NULL')
        right_rows = cur.fetchone()[0]

        cur.execute(f'''
            SELECT COUNT(*) FROM "{left_table}" l
            INNER JOIN "{right_table}" r ON l."{left_key}" = r."{right_key}"
        ''')
        joined_rows = cur.fetchone()[0]

        left_is_unique = (left_distinct == left_rows)
        right_is_unique = (right_distinct == right_rows)

        if left_is_unique and right_is_unique:
            cardinality = "one_to_one"
        elif left_is_unique and not right_is_unique:
            cardinality = "one_to_many"
        elif not left_is_unique and right_is_unique:
            cardinality = "many_to_one"
        else:
            cardinality = "many_to_many"

        return {
            "cardinality": cardinality,
            "left_distinct_keys": left_distinct,
            "left_total_rows": left_rows,
            "right_distinct_keys": right_distinct,
            "right_total_rows": right_rows,
            "joined_total_rows": joined_rows,
            "duplication_factor": round(joined_rows / max(1, left_distinct), 2),
        }

    def execute_query(self, sql: str, params: tuple = ()) -> dict[str, Any]:
        """Executes a read-only SQL query and measures execution time."""
        clean_sql = sql.strip()
        if not re.match(r"^(SELECT|WITH)\b", clean_sql, flags=re.IGNORECASE):
            raise PermissionError("Only read-only SELECT and WITH queries are permitted in the analytical engine.")

        start = time.perf_counter()
        cur = self.conn.cursor()
        cur.execute(clean_sql, params)
        rows = cur.fetchall()
        dur = round((time.perf_counter() - start) * 1000, 2)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        return {
            "columns": columns,
            "rows": [dict(r) for r in rows],
            "row_count": len(rows),
            "duration_ms": dur,
        }

    def compile_and_execute_rule(self, rule: MetricRule) -> MetricResult:
        """Compiles declarative MetricRule into deterministic SQL and executes it."""
        start = time.perf_counter()
        table = rule.source_table
        if table not in self.table_metadata:
            # Try to resolve table by filename or sheet
            matched = next(
                (t for t, meta in self.table_metadata.items() if table.lower() in meta["filename"].lower() or table.lower() in t.lower()),
                None
            )
            if matched:
                table = matched
            else:
                return MetricResult(
                    computed_value="ERROR",
                    status="error",
                    error_message=f"Source table '{rule.source_table}' not found in database.",
                )

        entity_col = rule.entity_identifier
        # Map original column name to sanitized if needed
        col_map = self.column_name_map.get(table, {})
        rev_map = {v.casefold(): k for k, v in col_map.items()}
        if entity_col.casefold() in rev_map:
            entity_col = rev_map[entity_col.casefold()]

        # Build WHERE clauses
        where_clauses = []
        params = []
        for f in rule.filters:
            col = f.column
            if col.casefold() in rev_map:
                col = rev_map[col.casefold()]
            op = f.operator.lower()
            val = f.value
            if op == "eq":
                where_clauses.append(f'LOWER("{col}") = ?')
                params.append(str(val).casefold())
            elif op == "in" and isinstance(val, (list, tuple)):
                placeholders = ", ".join(["?"] * len(val))
                where_clauses.append(f'LOWER("{col}") IN ({placeholders})')
                params.extend([str(v).casefold() for v in val])
            elif op == "contains":
                where_clauses.append(f'LOWER("{col}") LIKE ?')
                params.append(f"%{str(val).casefold()}%")
            elif op == "gte":
                where_clauses.append(f'"{col}" >= ?')
                params.append(str(val))
            elif op == "lte":
                where_clauses.append(f'"{col}" <= ?')
                params.append(str(val))
            elif op == "between" and isinstance(val, (list, tuple)) and len(val) == 2:
                where_clauses.append(f'"{col}" BETWEEN ? AND ?')
                params.extend([str(val[0]), str(val[1])])
            elif op == "is_not_null":
                where_clauses.append(f'("{col}" IS NOT NULL AND "{col}" != "")')
            elif op == "is_null":
                where_clauses.append(f'("{col}" IS NULL OR "{col}" = "")')

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Build Aggregation
        agg = rule.aggregation.lower()
        if agg == "distinct_count":
            select_expr = f'COUNT(DISTINCT "{entity_col}")'
        elif agg == "count":
            select_expr = 'COUNT(*)'
        elif agg == "sum":
            select_expr = f'SUM(CAST("{entity_col}" AS REAL))'
        elif agg == "average":
            select_expr = f'AVG(CAST("{entity_col}" AS REAL))'
        else:
            select_expr = f'COUNT(DISTINCT "{entity_col}")'

        main_sql = f'SELECT {select_expr} as val, COUNT(*) as evidence_rows FROM "{table}" {where_sql}'
        
        try:
            cur = self.conn.cursor()
            cur.execute(main_sql, params)
            res = cur.fetchone()
            computed_val = res[0] if res else 0
            evidence_rows = res[1] if res else 0

            # Get sample provenance rows
            sample_sql = f'SELECT "__source_file__", "__sheet_name__", "__excel_row__", "{entity_col}" FROM "{table}" {where_sql} LIMIT 10'
            cur.execute(sample_sql, params)
            samples = [dict(r) for r in cur.fetchall()]

            dur = round((time.perf_counter() - start) * 1000, 2)
            numeric_val = float(computed_val) if computed_val is not None else 0.0

            return MetricResult(
                computed_value=computed_val,
                numeric_value=numeric_val,
                numerator=int(numeric_val) if numeric_val.is_integer() else numeric_val,
                denominator=None,
                distinct_entities=int(numeric_val),
                executed_sql=main_sql,
                execution_ms=dur,
                evidence_row_count=evidence_rows,
                provenance_samples=samples,
                status="success",
            )
        except Exception as exc:
            return MetricResult(
                computed_value="ERROR",
                status="error",
                error_message=str(exc),
                executed_sql=main_sql,
            )
