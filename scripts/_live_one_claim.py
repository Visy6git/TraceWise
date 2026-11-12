"""Fast single-claim live validation of the Stage-2 rules harness against Bedrock.

Mirrors the orchestrator's per-claim goal, runs the live harness, then executes the
generated analysis.py in the sandbox and prints the verification evidence.

    env -u AWS_BEARER_TOKEN_BEDROCK .venv/Scripts/python.exe -m scripts._live_one_claim <run_id> <claim_id>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)

from app.harness.paths import strip_extended_prefix  # noqa: E402
from app.harness.runner import run_harness_task  # noqa: E402
from app.services.database import default_claim_repo, default_run_repo  # noqa: E402
from app.services.sandbox_client import default_sandbox  # noqa: E402
from app.services.storage import default_storage  # noqa: E402
from app.stages.stage_2_rules.orchestrator import (  # noqa: E402
    _gather_relevant_source_md,
    _load_rule_prompt,
    _load_source_markdown_map,
)


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "bcfc0437801b41f89dfd496d4f0ea15a"
    claim_id = sys.argv[2] if len(sys.argv) > 2 else "CLM-0001"

    run = default_run_repo.get_run(run_id)
    claim = default_claim_repo.get_claim(run_id, claim_id)
    source_paths = run.get("source_object_ids") or []
    per_file_mds, master_md = _load_source_markdown_map(run_id)
    relevant_md = _gather_relevant_source_md(claim, per_file_mds, master_md)
    rule_prompt = _load_rule_prompt()

    run_base = strip_extended_prefix(default_storage.run_dir(run_id)).resolve()
    ws_dir = run_base / "stage_2_rules" / "_oneclaim" / claim_id
    ws_dir.mkdir(parents=True, exist_ok=True)

    mapped = claim.get("source_document_mapped") or []
    matched_src = next((s for s in source_paths if Path(s).name in mapped), source_paths[0] if source_paths else "")
    src_parent = strip_extended_prefix(Path(matched_src).parent).resolve() if matched_src else ws_dir
    readonly_dirs = sorted({strip_extended_prefix(Path(s).parent).resolve() for s in source_paths})

    full = {
        "claim_id": claim_id,
        "section_number": claim.get("section_number"),
        "parent_claim": claim.get("parent_claim"),
        "children_claims": claim.get("children_claims") or [],
        "search_criteria": claim.get("search_criteria") or "",
        "source_document_mapped": mapped,
        "evidence_hint": claim.get("evidence_hint") or {},
    }
    goal = (
        f"Verify clinical claim `{claim_id}` inside workspace `{ws_dir}`.\n\n"
        f"## Full Claim Details\n```json\n{json.dumps(full, indent=2)}\n```\n\n"
        f"## Detailed Source File Markdown Summary\n{relevant_md}\n\n"
        "Instructions:\n"
        "1. Read files as needed; write `plan.md`, `analysis.py`, and `tests/test_analysis.py` using `write_file`.\n"
        "2. `analysis.py` MUST read source file(s) from `os.environ['SOURCE_INPUT_DIR']`, verify the parent_claim "
        "and children_claims, and write `result.json` + `evidence_bundle.json` with `verified`, `computed_value`, "
        "`reported_value`, `parent_verified`, `children_results`.\n"
        "3. `analysis.py` MUST ALSO write `claim_data.json` with the ACTUAL source rows backing each claim: "
        '{"claim_id": <id>, "parent": {"label": <desc>, "source_file": <file>, "sheet": <sheet|null>, '
        '"row_count": <int>, "columns": [<cols>], "rows": [<=200 row objects], "truncated": <bool>}, '
        '"children": [{"child_claim_id": <id>, "label": <desc>, "source_file": <file>, "sheet": <sheet>, '
        '"row_count": <int>, "columns": [...], "rows": [...], "truncated": <bool>}]}. Parent rows = exact rows '
        "producing computed_value; child rows = rows producing that child's value. Pick dedup key + filter/descriptive "
        "columns (not all). Convert NaN->null; cast scalars to str/int/float; cap rows at 200.\n"
        "4. Execute `python analysis.py` and `python -m pytest tests/test_analysis.py -q` via `shell`. Fix errors before finishing."
    )

    print(f"RUN {run_id} CLAIM {claim_id}  reported={claim.get('reported_value')}  mapped={mapped}")
    print(f"SOURCE_INPUT_DIR={src_parent}")
    res = run_harness_task(
        run_id=run_id,
        stage="rules",
        agent_id=f"RuleHarness-{claim_id}",
        goal=goal,
        workspace_dir=ws_dir,
        readonly_dirs=readonly_dirs,
        env_vars={"SOURCE_INPUT_DIR": str(src_parent), "RUN_ID": run_id, "CLAIM_ID": claim_id},
        developer_instructions=rule_prompt,
        max_turns=24,
    )
    print("\n==== HARNESS RESULT ====")
    print(f"success={res.success} turns={res.turns} tool_calls={res.tool_calls_count} elapsed={res.elapsed_seconds}s")
    print(f"error={res.error}")
    print(f"files_written={res.files_written}")

    print("\n==== TOOL CALLS (live Bedrock) ====")
    for h in res.tool_history:
        if h.get("event") == "start":
            print(f"  -> {h['tool']}: {json.dumps(h.get('args'))[:160]}")

    if (ws_dir / "analysis.py").exists():
        exec_result = default_sandbox.execute(
            run_id=run_id, claim_id=claim_id, script_path="analysis.py",
            workspace_dir=ws_dir, source_input_dir=src_parent,
        )
        print("\n==== SANDBOX RE-EXECUTION ====")
        print(f"exit_code={exec_result['exit_code']} status={exec_result['status']}")
        print(f"stdout={exec_result['stdout'][:500]}")
        if exec_result.get("result_data"):
            print("result.json:\n" + json.dumps(exec_result["result_data"], indent=2)[:900])
    else:
        print("\nNO analysis.py PRODUCED")

    # ---- Validate claim_data.json through the real API normalizer ----
    from app.api.claims import _normalize_table

    cd_path = ws_dir / "claim_data.json"
    print("\n==== CLAIM_DATA.JSON (UI data feature) ====")
    if cd_path.exists():
        cd = json.loads(cd_path.read_text(encoding="utf-8"))
        parent = _normalize_table(cd.get("parent"))
        if parent:
            print(f"PARENT: label={parent['label'][:80]!r}")
            print(f"  source={parent['source_file']} sheet={parent['sheet']} row_count={parent['row_count']} truncated={parent['truncated']}")
            print(f"  columns={parent['columns']}")
            print(f"  first_row={json.dumps(parent['rows'][0]) if parent['rows'] else None}")
        for ch in (cd.get("children") or []):
            n = _normalize_table(ch)
            if n:
                print(f"CHILD {ch.get('child_claim_id')}: label={n['label'][:70]!r} row_count={n['row_count']} cols={len(n['columns'])} first_row={json.dumps(n['rows'][0]) if n['rows'] else None}")
    else:
        print("NO claim_data.json PRODUCED")


if __name__ == "__main__":
    main()
