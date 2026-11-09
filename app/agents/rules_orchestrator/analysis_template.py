"""PLACEHOLDER analysis script for the TraceWise isolated sandbox.

HOW THE SANDBOX RUNS THIS
-------------------------
The Rules agent writes a file named ``analysis.py`` into the claim workspace,
then the sandbox executes it as a fresh subprocess:

    python analysis.py          # cwd == the claim workspace

Environment variables the sandbox injects (see app/services/sandbox_client.py):
    SOURCE_INPUT_DIR     directory holding the immutable source workbooks (READ-ONLY)
    CLAIM_WORKSPACE_DIR  the current working directory — write outputs HERE only
    CLAIM_ID, RUN_ID     identifiers for this claim / run

OUTPUT CONTRACT (required)
--------------------------
The script MUST write ``result.json`` in the workspace containing at least:
    {"claim_id", "computed_value", "unit", "source_file", "status"}
Anything printed to stdout/stderr is captured into the execution log. Writing a
``diagnostics.json`` with assumptions/unresolved questions is encouraged.

RULES
-----
- Pre-installed libraries you may import: pandas, numpy, openpyxl, duckdb.
- Read ONLY from SOURCE_INPUT_DIR; write ONLY inside the workspace.
- No network, no credentials, no subprocesses.
- CSMR exports have a banner/preamble ABOVE the real header — you MUST skip to the
  real header row (``header_row_index`` from the claim's verification_plan), otherwise
  the columns come back as col_0, col_1, ... and nothing can be found.
"""
import json
import os

import pandas as pd

CLAIM_ID = os.environ.get("CLAIM_ID", "CLM-XXXX")
SRC_DIR = os.environ.get("SOURCE_INPUT_DIR", ".")

# --- 1) From the claim's verification_plan: exact file, sheet and header offset ---
SOURCE_FILE = "03_case_Cardiac failure_CSMR.xlsx"
SHEET = "CSMR Case_2"
HEADER_ROW_INDEX = 5  # 0-based index of the REAL header row (skip the preamble above it)


def main() -> None:
    path = os.path.join(SRC_DIR, SOURCE_FILE)

    # --- 2) Read with the correct header (skiprows drops the banner/preamble) ---
    df = pd.read_excel(path, sheet_name=SHEET, skiprows=HEADER_ROW_INDEX, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    # --- 3) Apply the EXACT filters named in the verification_plan ---
    #        (use the exact column names and categorical values from the source map)
    filters_applied = []
    # Example — distinct serious cases:
    # df = df[df["Seriousness"].str.strip() == "Yes"]
    # filters_applied.append("Seriousness == 'Yes'")

    # --- 4) Aggregate per the plan (here: distinct count of the dedup key) ---
    DEDUP_KEY = "Case Number"
    computed_value = int(df[DEDUP_KEY].dropna().str.strip().nunique())

    # --- 5) Write the required result.json (and optional diagnostics) ---
    with open("result.json", "w", encoding="utf-8") as f:
        json.dump({
            "claim_id": CLAIM_ID,
            "computed_value": computed_value,
            "unit": "cases",
            "source_file": SOURCE_FILE,
            "sheet": SHEET,
            "header_row_index": HEADER_ROW_INDEX,
            "filters_applied": filters_applied,
            "dedup_key": DEDUP_KEY,
            "status": "computed",
        }, f, indent=2)

    with open("diagnostics.json", "w", encoding="utf-8") as f:
        json.dump({"row_count_after_filters": int(len(df)), "unresolved_semantics": []}, f, indent=2)

    print(f"{CLAIM_ID}: computed_value={computed_value}")


if __name__ == "__main__":
    main()
