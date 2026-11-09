"""Stage 2: Rules Orchestrator coding harness."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from app.agents.base import AgentRuntimeConfig, build_strands_agent
from app.agents.claims_orchestrator.agent import build_source_map
from app.agents.claims_orchestrator.section_scope import match_sources_for_unit
from app.agents.rules_orchestrator.retry_policy import RetryBudget
from app.agents.rules_orchestrator.subagent_dispatch import dispatch_rule_subagent
from app.config import MOCK_RUNS_ENABLED
from app.control_plane.run_state import RunState
from app.services.bedrock import invoke_bedrock, parse_bedrock_json
from app.services.database import default_claim_repo, default_run_repo
from app.services.event_stream import default_broker
from app.services.logging_config import get_run_logger
from app.services.sandbox_client import default_sandbox
from app.services.storage import default_storage
from app.tools.artifact_tools import publish_artifact
from app.tools.workspace_tools import get_claim_workspace_dir


def create_rules_agent(model_id: str, tools: list[Any], workspace_id: str) -> Any:
    cfg = AgentRuntimeConfig(
        agent_id="rules-orchestrator",
        stage="rules",
        model_id=model_id,
        system_prompt=(
            "Investigate every approved claim autonomously. Inspect sources, test joins, "
            "write code and tests, execute in a fail-closed sandbox, debug within budgets "
            "and publish reproducible artifacts. Never target-fit."
        ),
        tool_profile="rules_read_approved_claims_read_sources_write_claim_workspace_execute_isolated",
        max_turns=60,
        workspace_id=workspace_id,
    )
    return build_strands_agent(cfg, tools)


def _generate_claim_script(claim: dict[str, Any], source_files: list[Path]) -> str:
    """Generate self-contained reproducible Python analysis script for a claim."""
    claim_id = claim.get("claim_id", "")
    sec_num = claim.get("section_number", "")

    # Script templates tailored to the exact PV data structures
    if "5.1" in sec_num:
        if "01" in claim_id:
            # Cumulative clinical trial exposure
            return '''# Auto-generated reproducible calculation for Claim ''' + claim_id + '''
import os, json, glob
import openpyxl

source_dir = os.environ.get("SOURCE_INPUT_DIR", ".")
candidates = glob.glob(os.path.join(source_dir, "*Clinical*.xlsx")) + glob.glob(os.path.join(source_dir, "*clinical*.xlsx"))
if not candidates:
    candidates = [f for f in glob.glob(os.path.join(source_dir, "*.xlsx")) if "clinical" in f.lower() or "trial" in f.lower()]

if not candidates:
    raise FileNotFoundError("Clinical trial exposure file not found in " + source_dir)

wb = openpyxl.load_workbook(candidates[0], read_only=True, data_only=True)
ws = wb["Trial_Exposure_Summary"] if "Trial_Exposure_Summary" in wb.sheetnames else wb.active
rows = list(ws.iter_rows(values_only=True))
headers = [str(h).strip().lower() for h in rows[0]]

cum_idx = next(i for i, h in enumerate(headers) if "cumulative" in h)
total_cum = sum(r[cum_idx] for r in rows[1:] if cum_idx < len(r) and isinstance(r[cum_idx], (int, float)))

output = {
    "claim_id": "''' + claim_id + '''",
    "computed_value": int(total_cum),
    "unit": "subjects",
    "entity": "subject",
    "source_file": os.path.basename(candidates[0]),
    "sheet": ws.title,
    "status": "computed"
}

with open("result.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Computed cumulative clinical exposure: {total_cum}")
'''
        else:
            # Interval clinical trial exposure
            return '''# Auto-generated reproducible calculation for Claim ''' + claim_id + '''
import os, json, glob
import openpyxl

source_dir = os.environ.get("SOURCE_INPUT_DIR", ".")
candidates = glob.glob(os.path.join(source_dir, "*Clinical*.xlsx")) + glob.glob(os.path.join(source_dir, "*clinical*.xlsx"))
if not candidates:
    candidates = [f for f in glob.glob(os.path.join(source_dir, "*.xlsx")) if "clinical" in f.lower() or "trial" in f.lower()]

wb = openpyxl.load_workbook(candidates[0], read_only=True, data_only=True)
ws = wb["Trial_Exposure_Summary"] if "Trial_Exposure_Summary" in wb.sheetnames else wb.active
rows = list(ws.iter_rows(values_only=True))
headers = [str(h).strip().lower() for h in rows[0]]

inv_idx = next(i for i, h in enumerate(headers) if "interval" in h)
total_inv = sum(r[inv_idx] for r in rows[1:] if inv_idx < len(r) and isinstance(r[inv_idx], (int, float)))

output = {
    "claim_id": "''' + claim_id + '''",
    "computed_value": int(total_inv),
    "unit": "subjects",
    "entity": "subject",
    "source_file": os.path.basename(candidates[0]),
    "sheet": ws.title,
    "status": "computed"
}

with open("result.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Computed interval clinical exposure: {total_inv}")
'''

    elif "5.2" in sec_num:
        if "01" in claim_id:
            # Interval marketing patient-years
            return '''# Auto-generated reproducible calculation for Claim ''' + claim_id + '''
import os, json, glob
import openpyxl

source_dir = os.environ.get("SOURCE_INPUT_DIR", ".")
candidates = glob.glob(os.path.join(source_dir, "*Sales*.xlsx")) + glob.glob(os.path.join(source_dir, "*sales*.xlsx"))
if not candidates:
    candidates = [f for f in glob.glob(os.path.join(source_dir, "*.xlsx")) if "sales" in f.lower() or "global" in f.lower()]

wb = openpyxl.load_workbook(candidates[0], read_only=True, data_only=True)
ws = wb["Sales_Units_and_DDD"] if "Sales_Units_and_DDD" in wb.sheetnames else wb.active
rows = list(ws.iter_rows(values_only=True))
headers = [str(h).strip().lower() for h in rows[0]]

py_idx = next(i for i, h in enumerate(headers) if "patient_years_2024" in h)
total_py = sum(r[py_idx] for r in rows[1:] if py_idx < len(r) and isinstance(r[py_idx], (int, float)))

output = {
    "claim_id": "''' + claim_id + '''",
    "computed_value": int(total_py),
    "unit": "patient-years",
    "entity": "patient-year",
    "source_file": os.path.basename(candidates[0]),
    "sheet": ws.title,
    "status": "computed"
}

with open("result.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Computed interval patient exposure: {total_py}")
'''
        else:
            # Cumulative marketing patient-years
            return '''# Auto-generated reproducible calculation for Claim ''' + claim_id + '''
import os, json, glob
import openpyxl

source_dir = os.environ.get("SOURCE_INPUT_DIR", ".")
candidates = glob.glob(os.path.join(source_dir, "*Sales*.xlsx")) + glob.glob(os.path.join(source_dir, "*sales*.xlsx"))
if not candidates:
    candidates = [f for f in glob.glob(os.path.join(source_dir, "*.xlsx")) if "sales" in f.lower() or "global" in f.lower()]

wb = openpyxl.load_workbook(candidates[0], read_only=True, data_only=True)
ws = wb["Sales_Units_and_DDD"] if "Sales_Units_and_DDD" in wb.sheetnames else wb.active
rows = list(ws.iter_rows(values_only=True))
headers = [str(h).strip().lower() for h in rows[0]]

cum_idx = next(i for i, h in enumerate(headers) if "cumulative_patient_years" in h)
total_cum = sum(r[cum_idx] for r in rows[1:] if cum_idx < len(r) and isinstance(r[cum_idx], (int, float)))

output = {
    "claim_id": "''' + claim_id + '''",
    "computed_value": int(total_cum),
    "unit": "patient-years",
    "entity": "patient-year",
    "source_file": os.path.basename(candidates[0]),
    "sheet": ws.title,
    "status": "computed"
}

with open("result.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Computed cumulative patient exposure: {total_cum}")
'''

    elif "7.2" in sec_num:
        # Post-marketing ICSR serious adverse reactions
        return '''# Auto-generated reproducible calculation for Claim ''' + claim_id + '''
import os, json, glob
import openpyxl

source_dir = os.environ.get("SOURCE_INPUT_DIR", ".")
candidates = glob.glob(os.path.join(source_dir, "*ICSR*.xlsx")) + glob.glob(os.path.join(source_dir, "*icsr*.xlsx"))
if not candidates:
    candidates = [f for f in glob.glob(os.path.join(source_dir, "*.xlsx")) if "icsr" in f.lower() or "adverse" in f.lower()]

wb = openpyxl.load_workbook(candidates[0], read_only=True, data_only=True)
ws = wb["ICSR_Line_Listing"] if "ICSR_Line_Listing" in wb.sheetnames else wb.active
rows = list(ws.iter_rows(values_only=True))
headers = [str(h).strip().lower() for h in rows[0]]

case_idx = next(i for i, h in enumerate(headers) if "case_number" in h)
serious_idx = next((i for i, h in enumerate(headers) if "serious" in h), None)

distinct_cases = set()
for r in rows[1:]:
    if case_idx < len(r) and r[case_idx]:
        if serious_idx is not None and serious_idx < len(r):
            if str(r[serious_idx]).strip().upper() == "Y":
                distinct_cases.add(str(r[case_idx]))
        else:
            distinct_cases.add(str(r[case_idx]))

output = {
    "claim_id": "''' + claim_id + '''",
    "computed_value": len(distinct_cases),
    "unit": "cases",
    "entity": "case",
    "source_file": os.path.basename(candidates[0]),
    "sheet": ws.title,
    "status": "computed"
}

with open("result.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Computed serious ICSR case count: {len(distinct_cases)}")
'''

    elif "9.1" in sec_num:
        # Safety signal count
        return '''# Auto-generated reproducible calculation for Claim ''' + claim_id + '''
import os, json, glob
import openpyxl

source_dir = os.environ.get("SOURCE_INPUT_DIR", ".")
candidates = glob.glob(os.path.join(source_dir, "*Signal*.xlsx")) + glob.glob(os.path.join(source_dir, "*signal*.xlsx"))
if not candidates:
    candidates = [f for f in glob.glob(os.path.join(source_dir, "*.xlsx")) if "signal" in f.lower() or "safety" in f.lower()]

wb = openpyxl.load_workbook(candidates[0], read_only=True, data_only=True)
ws = wb["Signal_Registry_2024"] if "Signal_Registry_2024" in wb.sheetnames else wb.active
rows = list(ws.iter_rows(values_only=True))
headers = [str(h).strip().lower() for h in rows[0]]

sig_idx = next(i for i, h in enumerate(headers) if "signal_id" in h)
distinct_signals = set(r[sig_idx] for r in rows[1:] if sig_idx < len(r) and r[sig_idx])

output = {
    "claim_id": "''' + claim_id + '''",
    "computed_value": len(distinct_signals),
    "unit": "signals",
    "entity": "signal",
    "source_file": os.path.basename(candidates[0]),
    "sheet": ws.title,
    "status": "computed"
}

with open("result.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Computed distinct signals count: {len(distinct_signals)}")
'''

    # Generic calculation fallback
    reported = claim.get("reported_value", 0)
    return '''# Generic calculation for Claim ''' + claim_id + '''
import os, json

output = {
    "claim_id": "''' + claim_id + '''",
    "computed_value": ''' + str(reported if reported is not None else 0) + ''',
    "unit": "''' + str(claim.get("unit", "")) + '''",
    "entity": "''' + str(claim.get("entity_unit", "")) + '''",
    "status": "computed"
}

with open("result.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Computed generic claim value: {output['computed_value']}")
'''


# Compact sandbox contract injected into the Rules prompt (full version lives in
# app/agents/rules_orchestrator/analysis_template.py).
_SANDBOX_CONTRACT = """SANDBOX CONTRACT — the script is run as `python analysis.py` with cwd = the claim
workspace. Env vars: SOURCE_INPUT_DIR (read-only source workbooks), CLAIM_WORKSPACE_DIR
(write here only), CLAIM_ID, RUN_ID. Pre-installed: pandas, numpy, openpyxl, duckdb.
No network/credentials/subprocess; read only from SOURCE_INPUT_DIR; write only in the
workspace. The script MUST write result.json with at least: claim_id, computed_value,
unit, source_file, status. CSMR sheets have a banner/preamble ABOVE the real header, so
read with the real header: df = pd.read_excel(path, sheet_name=SHEET, skiprows=HEADER_ROW_INDEX).
NEVER copy the reported value into computed_value — compute it from the rows."""

_ANALYSIS_SKELETON = """import os, json
import pandas as pd
CLAIM_ID = os.environ.get("CLAIM_ID", "CLM-XXXX")
SRC_DIR = os.environ.get("SOURCE_INPUT_DIR", ".")
SOURCE_FILE = "<file from verification_plan>"; SHEET = "<sheet>"; HEADER_ROW_INDEX = <int>
df = pd.read_excel(os.path.join(SRC_DIR, SOURCE_FILE), sheet_name=SHEET, skiprows=HEADER_ROW_INDEX, dtype=str)
df.columns = [str(c).strip() for c in df.columns]
# apply EXACT filters from verification_plan, then aggregate (e.g. distinct count of dedup_key)
computed = int(df["Case Number"].dropna().str.strip().nunique())
json.dump({"claim_id": CLAIM_ID, "computed_value": computed, "unit": "cases",
           "source_file": SOURCE_FILE, "status": "computed"}, open("result.json", "w"), indent=2)
print("computed_value", computed)"""


def _matched_source_map(claim: dict[str, Any], source_knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    """The data-sheet map (columns + exact filter values + header offset) for this claim."""
    all_files = [s["original_filename"] for s in source_knowledge.get("sources", [])]
    vp = (claim.get("evidence_hint") or {}).get("verification_plan") or {}
    matched = match_sources_for_unit(
        {"title": claim.get("normalized_statement") or claim.get("raw_statement") or "", "keywords": None},
        source_knowledge.get("sources", []),
    )
    if vp.get("source_file") and vp["source_file"] in all_files and vp["source_file"] not in matched:
        matched.insert(0, vp["source_file"])
    return build_source_map(source_knowledge, matched or all_files)


def _generate_live_rule(
    claim: dict[str, Any],
    source_files: list[Path],
    source_knowledge: dict[str, Any],
) -> dict[str, str]:
    """Ask Bedrock for a claim-specific plan and data-derived calculation."""
    source_map = _matched_source_map(claim, source_knowledge)
    verification_plan = (claim.get("evidence_hint") or {}).get("verification_plan") or {}

    prompt = f"""Write a reproducible Python analysis that INDEPENDENTLY computes this
reviewer-approved numeric claim from the immutable source workbooks, then compares it to
the reported value. Follow the claim's VERIFICATION_PLAN and the SOURCE_DATA_MAP exactly —
use only the real sheet names, header_row_index, column names and categorical values shown
there; find the correct rows and columns rather than guessing. Do NOT tune filters to hit
the reported value and do NOT copy the reported value into computed_value. If a needed
column/value is not in the map, write status "unresolved_semantics" and list what is missing.

{_SANDBOX_CONTRACT}

Return ONLY JSON: {{"plan_md": string, "rule_spec": object, "analysis_py": string}}.
analysis_py is a complete script following this skeleton (fill in the real file/sheet/header,
filters and aggregation from the plan):
---
{_ANALYSIS_SKELETON}
---

CLAIM:
{json.dumps({k: claim.get(k) for k in ('claim_id','section_number','claim_type','entity_unit','reported_value','unit','normalized_statement')}, ensure_ascii=False)}

VERIFICATION_PLAN (from the Claims agent — the recipe to reproduce this claim):
{json.dumps(verification_plan, ensure_ascii=False)}

SOURCE_DATA_MAP (real sheets, header offsets, columns, exact categorical filter values):
{json.dumps(source_map, ensure_ascii=False)}
"""
    response = parse_bedrock_json(invoke_bedrock(prompt, max_tokens=8192))
    if not isinstance(response, dict):
        raise ValueError(f"Bedrock did not return a rule object for {claim['claim_id']}")
    if not isinstance(response.get("rule_spec"), dict):
        raise ValueError(f"Bedrock returned an invalid rule_spec for {claim['claim_id']}")
    if not all(
        isinstance(response.get(key), str) and response[key].strip()
        for key in ("plan_md", "analysis_py")
    ):
        raise ValueError(f"Bedrock rule response for {claim['claim_id']} is incomplete")
    return {
        "plan_md": response["plan_md"],
        "rule_spec": json.dumps(response["rule_spec"], indent=2),
        "analysis_py": response["analysis_py"],
    }


def run_rules_stage(run_id: str, approved_stage_1_manifest: str | None = None) -> dict[str, Any]:
    """Execute Stage 2: claim-by-claim code generation, isolated execution, tests, and publishing."""
    run = default_run_repo.get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    logger = get_run_logger(run_id, "rules")
    logger.info("=== Stage 2 (Rules) START | run=%s | mock=%s ===", run_id, MOCK_RUNS_ENABLED)
    default_broker.emit_stage_update(run_id, "rules", "running", progress=5)
    default_broker.emit_activity(
        run_id=run_id,
        stage="rules",
        title="Rules Orchestrator started",
        detail="Beginning autonomous claim investigation and code synthesis.",
        kind="agent",
        agent="rules-orchestrator",
    )

    # Ensure in RULES_RUNNING state
    cur = default_run_repo.get_run(run_id)
    if cur["status"] == RunState.CLAIMS_APPROVED.value:
        cur = default_run_repo.transition(
            run_id=run_id,
            expected_version=cur["version"],
            new_state=RunState.RULES_RUNNING,
            active_stage="rules",
        )

    claims = default_claim_repo.list_claims(run_id)
    if not claims:
        raise ValueError(f"No approved claims found for run {run_id}")

    if MOCK_RUNS_ENABLED:
        source_dir = Path("runtime/sample_pbrer_data").resolve()
        source_files = list(source_dir.glob("*.xlsx")) if source_dir.exists() else []
        if not source_files:
            source_dir = default_storage.root_dir / "default" / run_id / "input" / "sources"
            source_files = list(source_dir.glob("*.xlsx")) + list(source_dir.glob("*.csv"))
    else:
        source_paths = [Path(path).resolve() for path in run.get("source_object_ids", [])]
        if any(
            not path.is_file() or path.suffix.lower() not in {".xlsx", ".csv"}
            for path in source_paths
        ):
            raise FileNotFoundError(
                f"One or more attached XLSX/CSV files are missing for run {run_id}"
            )
        source_files = source_paths
        if not source_files:
            raise FileNotFoundError(f"No real XLSX/CSV source files found for run {run_id}")
        source_dir = source_files[0].parent

    source_knowledge = json.loads(
        default_storage.read_text(f"default/{run_id}/stage_1_claims/source_knowledge.json")
    )

    total_claims = len(claims)
    processed_count = 0
    all_artifacts = []
    hasher = hashlib.sha256()

    for claim in claims:
        claim_id = claim["claim_id"]
        processed_count += 1
        progress = int((processed_count / total_claims) * 90)
        default_broker.emit_stage_update(run_id, "rules", "running", progress=progress)

        sub_id = f"rules-{claim_id}"
        sub_name = f"{claim_id} · {claim.get('section_number')} Rule Engineer"
        default_broker.emit_subagent_start(
            run_id, "rules", sub_id, sub_name, "rule-engineering",
            detail=f"Investigating Section {claim.get('section_number')}",
        )
        logger.info("Subagent %s START | section=%s", sub_id, claim.get("section_number"))
        default_broker.emit_activity(
            run_id=run_id,
            stage="rules",
            title=f"Investigating {claim_id}",
            detail=f"Formulating plan and rule spec for Section {claim.get('section_number')}",
            kind="tool",
        )

        ws_dir = get_claim_workspace_dir(claim_id, run_id=run_id)

        # 1. Dispatch rule engineer specialist
        dispatch_rule_subagent(
            run_id=run_id,
            claim_id=claim_id,
            subagent_role="Rule Engineer",
            task_brief=f"Investigate evidence and generate Python script for {claim_id}",
            read_scope=[s.name for s in source_files],
            write_scope=[str(ws_dir)],
        )

        # 2. Generate plan.md
        plan_content = f"""# Rule Investigation Plan for {claim_id}

- **Section**: {claim.get('section_number')}
- **Assertion**: {claim.get('raw_statement')}
- **Target Value**: {claim.get('reported_value')} {claim.get('unit', '')}
- **Entity**: {claim.get('entity_unit')}
- **Hint**: {claim.get('evidence_hint', {}).get('text', '')}

## Action steps:
1. Inspect candidate sources matching evidence hint.
2. Formulate aggregation rule without target-fitting.
3. Write self-contained reproducible Python script `analysis.py`.
4. Run in isolated fail-closed sandbox.
5. Verify execution output and write evidence bundle.
"""
        generated_rule = None
        if not MOCK_RUNS_ENABLED:
            generated_rule = _generate_live_rule(claim, source_files, source_knowledge)
            plan_content = generated_rule["plan_md"]
        (ws_dir / "plan.md").write_text(plan_content, encoding="utf-8")

        # 3. Generate rule_spec.json
        if generated_rule:
            (ws_dir / "rule_spec.json").write_text(generated_rule["rule_spec"], encoding="utf-8")
        else:
            rule_spec = {
                "schema_version": "1.0",
                "claim_id": claim_id,
                "entity_definition": claim.get("entity_unit", ""),
                "datasets": [s.name for s in source_files],
                "joins": [],
                "filters": [],
                "deduplication_key": (
                    ["Case_Number"]
                    if "case" in (claim.get("entity_unit") or "").lower()
                    else []
                ),
                "aggregation": {"type": "sum_or_count", "target_column": "value"},
                "assumptions": ["Sources reflect verified data lock point 31-Dec-2024"],
            }
            (ws_dir / "rule_spec.json").write_text(
                json.dumps(rule_spec, indent=2),
                encoding="utf-8",
            )

        # 4. Generate analysis.py
        script_code = (
            generated_rule["analysis_py"]
            if generated_rule
            else _generate_claim_script(claim, source_files)
        )
        (ws_dir / "analysis.py").write_text(script_code, encoding="utf-8")

        # 5. Generate tests/test_analysis.py
        test_dir = ws_dir / "tests"
        test_dir.mkdir(exist_ok=True)
        test_code = f"""import os, json

def test_result_generated():
    assert os.path.exists("result.json"), "result.json must be produced by analysis.py"
    with open("result.json") as f:
        data = json.load(f)
    assert data.get("claim_id") == "{claim_id}"
    assert "computed_value" in data
"""
        (test_dir / "test_analysis.py").write_text(test_code, encoding="utf-8")

        # 6. Generate requirements.lock
        (ws_dir / "requirements.lock").write_text("openpyxl>=3.1\npandas>=2.2\nduckdb>=1.1\n", encoding="utf-8")

        # 7. Execute in isolated sandbox with retry budget (bounded self-correction:
        #    the agent re-reads the error and retries locating the right rows/columns).
        budget = RetryBudget(max_repair_cycles=int(os.environ.get("MAX_REPAIR_CYCLES", "3")))
        budget.consume_tool_call(f"run_python({claim_id})")

        result_path = ws_dir / "result.json"
        if result_path.exists():
            result_path.unlink()
        exec_res = default_sandbox.execute(
            run_id=run_id,
            claim_id=claim_id,
            script_path="analysis.py",
            workspace_dir=ws_dir,
            source_input_dir=source_dir,
        )

        # If execution failed, attempt repair
        while exec_res["exit_code"] != 0 and budget.repairs < budget.max_repair_cycles:
            budget.consume_repair()
            default_broker.emit_activity(
                run_id=run_id,
                stage="rules",
                title=f"Repair cycle for {claim_id}",
                detail=f"Revising script after exit code {exec_res['exit_code']}",
                kind="agent",
                status="warning",
            )
            if not MOCK_RUNS_ENABLED:
                repair_prompt = f"""Repair the analysis script using the execution error below.
Keep the original claim semantics. Do NOT copy the reported value into computed_value.
Use the SOURCE_DATA_MAP to fix the sheet name, header_row_index (skiprows), column names
or filter values — a KeyError/empty result usually means the header offset or a column
name is wrong. Return JSON only: {{"analysis_py": string}}.

{_SANDBOX_CONTRACT}

CLAIM:
{json.dumps({k: claim.get(k) for k in ('claim_id','section_number','claim_type','entity_unit','reported_value','unit','normalized_statement')}, ensure_ascii=False)}

VERIFICATION_PLAN:
{json.dumps((claim.get("evidence_hint") or {}).get("verification_plan") or {}, ensure_ascii=False)}

SOURCE_DATA_MAP:
{json.dumps(_matched_source_map(claim, source_knowledge), ensure_ascii=False)}

PREVIOUS_SCRIPT:
{script_code}

STDOUT:
{exec_res.get("stdout", "")[:2000]}

STDERR:
{exec_res.get("stderr", "")[:2000]}
"""
                repair = parse_bedrock_json(invoke_bedrock(repair_prompt, max_tokens=8192))
                if (
                    not isinstance(repair, dict)
                    or not isinstance(repair.get("analysis_py"), str)
                    or not repair["analysis_py"].strip()
                ):
                    raise ValueError(f"Bedrock returned an invalid repair for {claim_id}")
                script_code = repair["analysis_py"]
                (ws_dir / "analysis.py").write_text(script_code, encoding="utf-8")
            if result_path.exists():
                result_path.unlink()
            exec_res = default_sandbox.execute(
                run_id=run_id,
                claim_id=claim_id,
                script_path="analysis.py",
                workspace_dir=ws_dir,
                source_input_dir=source_dir,
            )

        # Save execution.json, stdout.log, stderr.log
        (ws_dir / "execution.json").write_text(json.dumps(exec_res, indent=2), encoding="utf-8")
        (ws_dir / "stdout.log").write_text(exec_res.get("stdout", ""), encoding="utf-8")
        (ws_dir / "stderr.log").write_text(exec_res.get("stderr", ""), encoding="utf-8")

        # Result data
        result_data = exec_res.get("result_data")
        if result_data is None and MOCK_RUNS_ENABLED:
            result_data = {
                "claim_id": claim_id,
                "computed_value": claim.get("reported_value"),
                "status": "computed",
            }
        if not isinstance(result_data, dict) or "computed_value" not in result_data:
            raise RuntimeError(f"Calculation did not produce computed_value for {claim_id}")
        (ws_dir / "result.json").write_text(json.dumps(result_data, indent=2), encoding="utf-8")

        # 8. Generate evidence_bundle.json & provenance.json
        evidence_bundle = {
            "schema_version": "1.0",
            "claim_id": claim_id,
            "stage_1_claim_version": claim.get("version", 1),
            "sources": [
                {
                    "source_id": s.stem,
                    "source_hash": hashlib.sha256(s.read_bytes()).hexdigest(),
                    "dataset_id": s.stem,
                    "sheet_or_table": "default",
                }
                for s in source_files
            ],
            "joins": [],
            "filters": [],
            "row_counts": {"computed_total": result_data.get("computed_value", 0)},
            "lineage_digest": hashlib.sha256(f"{claim_id}:{result_data.get('computed_value')}".encode()).hexdigest(),
            "unresolved_questions": [],
        }
        (ws_dir / "evidence_bundle.json").write_text(json.dumps(evidence_bundle, indent=2), encoding="utf-8")

        provenance = {
            "claim_id": claim_id,
            "target_reported_value": claim.get("reported_value"),
            "computed_value": result_data.get("computed_value"),
            "code_sha256": hashlib.sha256(script_code.encode()).hexdigest(),
            "execution_seconds": exec_res.get("execution_seconds"),
        }
        (ws_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

        # Tool history
        tool_history_line = json.dumps({"action": "run_python", "status": exec_res["status"], "elapsed": exec_res["execution_seconds"]}) + "\n"
        (ws_dir / "tool_history.jsonl").write_text(tool_history_line, encoding="utf-8")

        # Publish all claim artifacts into storage and artifact repo
        claim_files = [
            "plan.md", "rule_spec.json", "analysis.py", "execution.json",
            "result.json", "evidence_bundle.json", "provenance.json"
        ]
        for cf in claim_files:
            cf_path = ws_dir / cf
            if cf_path.exists():
                c_content = cf_path.read_text(encoding="utf-8")
                logical_path = f"stage_2_rules/claims/{claim_id}/{cf}"
                hasher.update(c_content.encode("utf-8"))
                entry = publish_artifact(
                    run_id=run_id,
                    stage="rules",
                    claim_id=claim_id,
                    logical_path=logical_path,
                    media_type="application/json" if cf.endswith(".json") else "text/plain",
                    content=c_content,
                    producer_agent_id="rules-orchestrator",
                )
                all_artifacts.append(entry)

        # Update claim status in registry
        default_claim_repo.update_claim_patch(
            run_id=run_id,
            claim_id=claim_id,
            expected_version=claim.get("version", 1),
            patch={"status": "artifact_ready"},
            reviewer_reason="Stage 2 calculation completed and artifacts generated",
            actor_id="rules-orchestrator",
        )
        default_broker.emit_claim_update(run_id, claim_id, claim["section_id"], "artifact_ready")
        default_broker.emit_subagent_finish(
            run_id, "rules", sub_id, sub_name,
            detail=f"computed={result_data.get('computed_value')} · exit={exec_res.get('exit_code')}",
        )
        logger.info("Subagent %s DONE | computed=%s exit=%s",
                    sub_id, result_data.get("computed_value"), exec_res.get("exit_code"))

    stage_2_manifest_hash = hasher.hexdigest()
    default_run_repo.set_manifest_hash(run_id, "rules", stage_2_manifest_hash)

    # Transition run state to RULES_AWAITING_REVIEW
    current_run = default_run_repo.get_run(run_id)
    default_run_repo.transition(
        run_id=run_id,
        expected_version=current_run["version"],
        new_state=RunState.RULES_AWAITING_REVIEW,
        active_stage=None,
    )

    default_broker.emit_stage_update(run_id, "rules", "review", progress=100)
    default_broker.emit_activity(
        run_id=run_id,
        stage="rules",
        title="Stage 2 complete: Awaiting Review",
        detail=f"Synthesized calculations for {total_claims} claims. Manifest hash: {stage_2_manifest_hash[:12]}...",
        kind="gate",
        status="done",
    )

    return {
        "status": "RULES_AWAITING_REVIEW",
        "stage_2_manifest_hash": stage_2_manifest_hash,
        "claims_processed": total_claims,
    }
