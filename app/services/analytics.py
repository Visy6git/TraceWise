"""Deterministic local analytical layer using DuckDB and Pandas."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


class AnalyticsService:
    def __init__(self):
        self.con = duckdb.connect(database=":memory:")

    def register_dataframe(self, table_name: str, df: pd.DataFrame) -> None:
        self.con.register(table_name, df)

    def load_dataset(self, file_path: str | Path, sheet_name: str | None = None) -> pd.DataFrame:
        path = Path(file_path).resolve()
        suffix = path.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            return pd.read_excel(str(path), sheet_name=sheet_name or 0)
        elif suffix == ".csv":
            return pd.read_csv(str(path))
        elif suffix == ".parquet":
            return pd.read_parquet(str(path))
        raise ValueError(f"Unsupported analytical file format: {suffix}")

    def profile_dataframe(self, df: pd.DataFrame, dataset_id: str) -> dict[str, Any]:
        total_rows = len(df)
        columns_profile = []
        candidate_keys = []

        for col in df.columns:
            series = df[col]
            null_count = int(series.isna().sum())
            null_fraction = float(null_count / total_rows) if total_rows > 0 else 0.0
            non_null = series.dropna()
            distinct_count = int(non_null.nunique())

            min_val = None
            max_val = None
            if not non_null.empty:
                try:
                    min_val = str(non_null.min())
                    max_val = str(non_null.max())
                except Exception:
                    pass

            samples = [str(x) for x in non_null.head(5).tolist()]

            # Candidate key criteria: zero nulls and distinct count matches row count
            if total_rows > 0 and null_count == 0 and distinct_count == total_rows:
                candidate_keys.append(str(col))

            inferred_type = str(series.dtype)
            columns_profile.append({
                "dataset_id": dataset_id,
                "original_name": str(col),
                "normalized_name": str(col).lower().replace(" ", "_"),
                "inferred_type": inferred_type,
                "null_count": null_count,
                "null_fraction": round(null_fraction, 4),
                "distinct_count": distinct_count,
                "min_value": min_val,
                "max_value": max_val,
                "sample_values": samples,
            })

        return {
            "dataset_id": dataset_id,
            "row_count": total_rows,
            "column_count": len(df.columns),
            "columns": columns_profile,
            "candidate_keys": candidate_keys,
        }

    def test_join_cardinality(
        self,
        left_df: pd.DataFrame,
        right_df: pd.DataFrame,
        left_keys: list[str],
        right_keys: list[str],
    ) -> dict[str, Any]:
        """Measure match/unmatched and duplicate expansion between two dataframes."""
        merged_inner = pd.merge(left_df, right_df, left_on=left_keys, right_on=right_keys, how="inner")
        merged_left = pd.merge(left_df, right_df, left_on=left_keys, right_on=right_keys, how="left", indicator=True)
        merged_right = pd.merge(left_df, right_df, left_on=left_keys, right_on=right_keys, how="right", indicator=True)

        left_rows = len(left_df)
        right_rows = len(right_df)
        matched_rows = len(merged_inner)
        unmatched_left = int((merged_left["_merge"] == "left_only").sum())
        unmatched_right = int((merged_right["_merge"] == "right_only").sum())

        dup_expansion = max(0, matched_rows - min(left_rows, right_rows))

        # Classify cardinality
        if left_rows == 0 or right_rows == 0:
            cardinality = "empty"
        elif matched_rows == left_rows and left_rows == right_rows:
            cardinality = "1:1"
        elif matched_rows >= left_rows:
            cardinality = "1:N"
        else:
            cardinality = "M:N"

        return {
            "left_keys": left_keys,
            "right_keys": right_keys,
            "tested_cardinality": cardinality,
            "left_rows": left_rows,
            "right_rows": right_rows,
            "matched_rows": matched_rows,
            "unmatched_left": unmatched_left,
            "unmatched_right": unmatched_right,
            "duplicate_expansion": dup_expansion,
            "accepted": dup_expansion == 0,
            "rationale": f"Tested join between {left_keys} and {right_keys}: {matched_rows} matched rows.",
        }

    def execute_bounded_query(self, query: str, max_rows: int = 100) -> list[dict[str, Any]]:
        # Enforce read-only select only
        clean_q = query.strip()
        if not clean_q.lower().startswith("select"):
            raise ValueError("Only SELECT queries are permitted in the analytical service")

        limited_query = f"SELECT * FROM ({clean_q}) LIMIT {max_rows}"
        df = self.con.execute(limited_query).fetchdf()
        return df.to_dict(orient="records")


default_analytics = AnalyticsService()
