"""Drive a live Stage-2 (rules) rerun on an existing run, all against live Bedrock.

Run with the stale Bedrock bearer token removed so boto3 uses the fresh default
profile SigV4 credentials:

    env -u AWS_BEARER_TOKEN_BEDROCK .venv/Scripts/python.exe -m scripts._live_rerun_stage2 <run_id>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Belt-and-suspenders: never let a stale bearer token hijack Bedrock auth.
os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)

from app.control_plane.run_state import RunState  # noqa: E402
from app.services.database import default_claim_repo, default_run_repo  # noqa: E402
from app.services.storage import default_storage  # noqa: E402
from app.stages.stage_2_rules.orchestrator import run_rules_stage  # noqa: E402


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "bcfc0437801b41f89dfd496d4f0ea15a"
    run = default_run_repo.get_run(run_id)
    if not run:
        print(f"RUN_NOT_FOUND {run_id}")
        return

    print(f"run_id={run_id} status={run['status']} version={run['version']} active_stage={run.get('active_stage')}")
    print(f"SANDBOX_BACKEND={os.environ.get('SANDBOX_BACKEND')} SANDBOX_REQUIRED={os.environ.get('SANDBOX_REQUIRED')}")
    print(f"bearer_token_present={'AWS_BEARER_TOKEN_BEDROCK' in os.environ}")

    stage_1_hash = run.get("stage_1_manifest_hash")
    if not stage_1_hash:
        print("NO_STAGE_1_MANIFEST — cannot run rules")
        return

    state = RunState(run["status"])
    # Move into RULES_RUNNING from whatever rerunnable state we are in.
    if state != RunState.RULES_RUNNING:
        run = default_run_repo.transition(
            run_id=run_id,
            expected_version=run["version"],
            new_state=RunState.RULES_RUNNING,
            active_stage="rules",
        )
        print(f"transitioned -> {run['status']} version={run['version']}")

    result = run_rules_stage(run_id, stage_1_hash)
    print("STAGE_RESULT:", json.dumps(result, indent=2))

    # Per-claim live evidence summary straight from the workspace.
    run_base = Path(default_storage.run_dir(run_id))
    claims_dir = run_base / "stage_2_rules" / "claims"
    print("\n==== PER-CLAIM LIVE EVIDENCE ====")
    for claim in default_claim_repo.list_claims(run_id):
        cid = claim["claim_id"]
        ws = claims_dir / cid
        has_py = (ws / "analysis.py").exists()
        has_result = (ws / "result.json").exists()
        vr = claim.get("verification_result") or {}
        computed = vr.get("parent_computed_value")
        reported = vr.get("parent_reported_value")
        print(
            f"{cid}: status={claim['status']:<11} analysis.py={has_py} result.json={has_result} "
            f"computed={computed} reported={reported}"
        )


if __name__ == "__main__":
    main()
