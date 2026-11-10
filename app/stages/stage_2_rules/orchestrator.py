"""Stage 2 Orchestrator: Per-claim verification via Agentic Harness + detailed source .md."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.config import MOCK_RUNS_ENABLED, is_live_llm_enabled
from app.control_plane.run_state import RunState
from app.harness.paths import strip_extended_prefix, to_extended_path
from app.harness.runner import HarnessRunResult, run_harness_task
from app.schemas.claim import ClaimStatus, VerificationResult
from app.services.database import default_artifact_repo, default_claim_repo, default_run_repo
from app.services.event_stream import default_broker
from app.services.sandbox_client import default_sandbox
from app.services.storage import default_storage


def _load_rule_prompt() -> str:
    p = Path(__file__).resolve().parents[2] / "prompts" / "rule_engineer.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _snapshot_hashes(paths: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for s in paths:
        p = to_extended_path(strip_extended_prefix(Path(s)).resolve())
        if p.exists() and p.is_file():
            out[str(strip_extended_prefix(Path(s)).resolve())] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _load_source_markdown_map(run_id: str) -> tuple[dict[str, str], str]:
    """Load detailed per-file .md summaries + master_source_summary.md from Stage 1 storage."""
    per_file: dict[str, str] = {}
    master_md = ""
    try:
        master_md = default_storage.read_text(f"default/{run_id}/stage_1_claims/master_source_summary.md")
    except Exception:
        pass

    try:
        sk_raw = default_storage.read_text(f"default/{run_id}/stage_1_claims/source_knowledge.json")
        sk = json.loads(sk_raw)
        md_paths: dict[str, str] = sk.get("per_file_md_paths") or {}
        for filename, logical_path in md_paths.items():
            try:
                per_file[filename] = default_storage.read_text(f"default/{run_id}/{logical_path}")
            except Exception:
                continue
    except Exception:
        pass

    return per_file, master_md


def _gather_relevant_source_md(
    claim: dict[str, Any],
    per_file_mds: dict[str, str],
    master_md: str,
) -> str:
    mapped: list[str] = claim.get("source_document_mapped") or []
    parts: list[str] = []
    matched_any = False
    for fn in mapped:
        if fn in per_file_mds:
            matched_any = True
            parts.append(per_file_mds[fn])
        else:
            low = fn.lower()
            for avail_fn, md_txt in per_file_mds.items():
                if low in avail_fn.lower() or avail_fn.lower() in low:
                    matched_any = True
                    parts.append(md_txt)
    if not matched_any:
        if per_file_mds:
            parts.extend(per_file_mds.values())
        elif master_md:
            parts.append(master_md)
    return "\n\n---\n\n".join(parts).strip() or "No source summary available."


def _values_match(reported: Any, computed: Any) -> bool:
    if computed is None or reported is None:
        return False
    r_str = str(reported).strip()
    if "/" in r_str:
        r_str = r_str.split("/", 1)[0].strip()
    try:
        r_num = float(r_str.replace(",", "").rstrip("%"))
        c_num = float(str(computed).replace(",", "").rstrip("%"))
        if r_num.is_integer() and c_num.is_integer():
            return int(r_num) == int(c_num)
        return abs(r_num - c_num) <= 0.15
    except ValueError:
        return r_str.lower() == str(computed).strip().lower()


def _write_deterministic_claim_files(
    *,
    ws_dir: Path,
    claim: dict[str, Any],
    primary_source_file: str,
    sheet_name: str,
    header_row_index: int,
    dedup_key: str,
) -> None:
    """Deterministic Python generator for mock/offline verification runs."""
    claim_id = claim["claim_id"]
    reported_val = claim.get("reported_value")
    children = claim.get("children_claims") or []
    search_criteria = claim.get("search_criteria") or ""

    plan_md = (
        f"# Verification Plan for {claim_id}\n\n"
        f"- **Parent Claim**: {claim.get('raw_statement')}\n"
        f"- **Reported Value**: `{reported_val}`\n"
        f"- **Search Criteria**: `{search_criteria}`\n"
        f"- **Mapped Source**: `{primary_source_file}` (sheet `{sheet_name}`, `header_row_index={header_row_index}`)\n"
        f"- **Dedup Key**: `{dedup_key}`\n"
        f"- **Children Claims ({len(children)})**: "
        + (", ".join(ch.get("raw_statement", "") for ch in children) if children else "None")
        + "\n"
    )
    (ws_dir / "plan.md").write_text(plan_md, encoding="utf-8")

    # Deterministic script that loads the actual mapped Excel/CSV using real coordinates,
    # filters where applicable (including filter_spec or text matching in mock datasets),
    # computes parent & children values, and writes result.json + evidence_bundle.json.
    analysis_py = f'''"""Stage 2 deterministic verification script for {claim_id}."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd

CLAIM_ID = {json.dumps(claim_id)}
SOURCE_FILE = {json.dumps(primary_source_file)}
SHEET_NAME = {json.dumps(sheet_name)}
HEADER_ROW_INDEX = {int(header_row_index)}
DEDUP_KEY = {json.dumps(dedup_key)}
PARENT_REPORTED = {json.dumps(str(reported_val) if reported_val is not None else "")}
CHILDREN = json.loads({json.dumps(json.dumps(children))})


def _num_from_reported(val) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if "/" in s:
        s = s.split("/", 1)[0].strip()
    s = s.replace(",", "").rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def _ext_path(p: Path) -> Path:
    s = str(p.resolve())
    ext_prefix = chr(92) * 2 + "?" + chr(92)
    if os.name == "nt" and len(s) >= 245 and not s.startswith(ext_prefix):
        return Path(ext_prefix + s)
    return p


def main() -> None:
    src_dir = Path(os.environ.get("SOURCE_INPUT_DIR", "."))
    src_path = _ext_path(src_dir / SOURCE_FILE)
    if SOURCE_FILE.lower().endswith(".csv"):
        df = pd.read_csv(src_path, skiprows=HEADER_ROW_INDEX, dtype=str)
    else:
        df = pd.read_excel(src_path, sheet_name=SHEET_NAME, skiprows=HEADER_ROW_INDEX, dtype=str)

    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")

    key_col = DEDUP_KEY if DEDUP_KEY in df.columns else df.columns[0]
    distinct_count = int(df[key_col].dropna().astype(str).str.strip().nunique())

    parent_target = _num_from_reported(PARENT_REPORTED)
    # Match against distinct count (or row count when dedup matches)
    computed_parent = distinct_count
    parent_verified = (parent_target is not None and abs(computed_parent - parent_target) <= 0.15)

    children_results = []
    all_children_ok = True
    for ch in CHILDREN:
        cid = ch.get("child_claim_id", "")
        c_rep = ch.get("reported_value")
        c_num = _num_from_reported(c_rep)
        rel = str(ch.get("relationship", "")).lower()

        # Check matching column heuristically in mock data (e.g. Seriousness == 'Yes', Death == 'Yes')
        c_comp = None
        if "fatal" in rel or "death" in rel:
            death_col = next((c for c in df.columns if "death" in c.lower() or "fatal" in c.lower()), None)
            if death_col:
                sub = df[df[death_col].fillna("").str.strip().str.lower().isin({{"yes", "y", "fatal", "1", "true"}})]
                c_comp = int(sub[key_col].dropna().nunique())
        elif "serious" in rel:
            ser_col = next((c for c in df.columns if "serious" in c.lower()), None)
            if ser_col:
                sub = df[df[ser_col].fillna("").str.strip().str.lower().isin({{"yes", "y", "serious", "1", "true"}})]
                c_comp = int(sub[key_col].dropna().nunique())
        elif "source" in rel:
            src_col = next((c for c in df.columns if "source" in c.lower()), None)
            if src_col:
                raw_stmt = str(ch.get("raw_statement", "")).strip()
                label_part = raw_stmt.split(":", 1)[0].strip().lower() if ":" in raw_stmt else ""
                series_low = df[src_col].fillna("").astype(str).str.strip().str.lower()
                if label_part and (series_low == label_part).any():
                    sub = df[series_low == label_part]
                elif label_part:
                    sub = df[series_low.str.contains(label_part, regex=False)]
                elif "spontaneous" in raw_stmt.lower():
                    sub = df[series_low.str.contains("spontaneous", regex=False)]
                else:
                    sub = df.iloc[0:0]
                c_comp = int(sub[key_col].dropna().nunique())

        c_ok = (c_comp is not None and c_num is not None and abs(c_comp - c_num) <= 0.15)
        if not c_ok:
            all_children_ok = False
        children_results.append({{
            "child_claim_id": cid,
            "raw_statement": ch.get("raw_statement"),
            "relationship": ch.get("relationship"),
            "reported_value": c_rep,
            "computed_value": c_comp,
            "verified": c_ok,
            "notes": f"Computed {{c_comp}} vs reported {{c_rep}}",
        }})

    verified = bool(parent_verified and (all_children_ok if CHILDREN else True))
    result = {{
        "claim_id": CLAIM_ID,
        "source_file": SOURCE_FILE,
        "sheet": SHEET_NAME,
        "header_row_index": HEADER_ROW_INDEX,
        "dedup_key": key_col,
        "reported_value": PARENT_REPORTED,
        "computed_value": computed_parent,
        "parent_verified": parent_verified,
        "children_results": children_results,
        "verified": verified,
        "status": "verified" if verified else "discrepancy",
    }}
    Path("result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    Path("evidence_bundle.json").write_text(json.dumps({{
        "claim_id": CLAIM_ID,
        "row_count": int(len(df)),
        "distinct_key_count": distinct_count,
        "verified": verified,
    }}, indent=2), encoding="utf-8")
    print(f"{{CLAIM_ID}}: computed={{computed_parent}} reported={{PARENT_REPORTED}} verified={{verified}}")


if __name__ == "__main__":
    main()
'''
    (ws_dir / "analysis.py").write_text(analysis_py, encoding="utf-8")

    tests_dir = ws_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_py = '''import json
from pathlib import Path


def test_result_json_exists_and_valid():
    p = Path("result.json")
    assert p.exists(), "result.json must be produced by analysis.py"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "computed_value" in data
    assert isinstance(data.get("verified"), bool)
'''
    (tests_dir / "test_analysis.py").write_text(test_py, encoding="utf-8")


def _publish_claim_artifact(
    run_id: str,
    claim_id: str,
    rel_path: str,
    media_type: str,
    content: str | bytes,
    producer: str = "Stage2RuleHarness",
) -> dict[str, Any]:
    logical_path = f"stage_2_rules/claims/{claim_id}/{rel_path}"
    stored = default_storage.put_derived(
        tenant_id="default",
        run_id=run_id,
        logical_path=logical_path,
        body=content,
    )
    artifact_id = f"art_{hashlib.md5(f'{run_id}:{logical_path}:rules'.encode()).hexdigest()[:12]}"
    entry = {
        "artifact_id": artifact_id,
        "run_id": run_id,
        "stage": "rules",
        "claim_id": claim_id,
        "logical_path": logical_path,
        "version": 1,
        "sha256": stored["sha256"],
        "media_type": media_type,
        "size_bytes": stored["size_bytes"],
        "producer_agent_id": producer,
        "status": "ready",
    }
    default_artifact_repo.add_artifact(entry)
    default_broker.emit_artifact_ready(run_id, "rules", entry)
    return entry


def run_rules_stage(run_id: str, expected_stage_1_manifest_hash: str) -> dict[str, Any]:
    run = default_run_repo.get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    if run.get("stage_1_manifest_hash") != expected_stage_1_manifest_hash:
        raise ValueError("Stage 1 manifest hash mismatch or missing; Stage 1 approval required")

    default_broker.emit_run_started(run_id, "rules")
    default_broker.emit_stage_update(run_id, "rules", "running", progress=5)

    claims = default_claim_repo.list_claims(run_id)
    if not claims:
        raise ValueError(f"No claims found for run {run_id}; cannot run Stage 2")

    per_file_mds, master_md = _load_source_markdown_map(run_id)
    rule_system_prompt = _load_rule_prompt()
    source_paths: list[str] = run.get("source_object_ids") or []
    baseline_hashes = _snapshot_hashes(source_paths)

    # Load source_knowledge.json for deterministic fallback coordinates
    sk_datasets: list[dict[str, Any]] = []
    try:
        sk_raw = default_storage.read_text(f"default/{run_id}/stage_1_claims/source_knowledge.json")
        sk_datasets = json.loads(sk_raw).get("datasets") or []
    except Exception:
        pass

    use_live = is_live_llm_enabled() and not MOCK_RUNS_ENABLED
    run_base = strip_extended_prefix(default_storage.run_dir(run_id)).resolve()

    verified_count = 0
    failed_count = 0
    discrepancy_count = 0
    claim_artifact_hashes: dict[str, str] = {}

    total_claims = len(claims)
    for idx, claim in enumerate(claims, start=1):
        claim_id = claim["claim_id"]
        claim["status"] = ClaimStatus.in_progress.value
        saved_in_progress = default_claim_repo.save_claim(run_id, claim)
        default_broker.emit_claim_update(run_id, saved_in_progress)

        default_broker.emit_activity(
            run_id=run_id,
            stage="rules",
            title=f"Verifying {claim_id} ({idx}/{total_claims})",
            detail=f"{claim.get('raw_statement', '')[:95]}",
            kind="agent",
            agent=f"RuleHarness-{claim_id}",
        )

        ws_dir = run_base / "stage_2_rules" / "claims" / claim_id
        ws_dir.mkdir(parents=True, exist_ok=True)

        # Gather relevant detailed .md file(s) & full claim details
        relevant_md = _gather_relevant_source_md(claim, per_file_mds, master_md)
        full_claim_details = {
            "claim_id": claim_id,
            "section_number": claim.get("section_number"),
            "section_title": claim.get("section_title"),
            "parent_claim": claim.get("parent_claim"),
            "children_claims": claim.get("children_claims") or [],
            "search_criteria": claim.get("search_criteria") or "",
            "source_document_mapped": claim.get("source_document_mapped") or [],
            "evidence_hint": claim.get("evidence_hint") or {},
        }
        (ws_dir / "claim_context.json").write_text(
            json.dumps(full_claim_details, indent=2), encoding="utf-8"
        )
        (ws_dir / "source_summary.md").write_text(relevant_md, encoding="utf-8")

        # Determine SOURCE_INPUT_DIR & readonly dirs
        mapped = claim.get("source_document_mapped") or []
        matched_src_path = next(
            (s for s in source_paths if Path(s).name in mapped),
            source_paths[0] if source_paths else "",
        )
        src_parent = (
            strip_extended_prefix(Path(matched_src_path).parent).resolve()
            if matched_src_path
            else ws_dir
        )
        readonly_dirs = sorted(
            {strip_extended_prefix(Path(s).parent).resolve() for s in source_paths}
        )

        tool_history: list[dict[str, Any]] = []
        if use_live:
            goal = (
                f"Verify clinical claim `{claim_id}` inside workspace `{ws_dir}`.\n\n"
                f"## Full Claim Details (Parent Claim, Children Claims, Search Criteria, Mapping, Hints)\n"
                f"```json\n{json.dumps(full_claim_details, indent=2)}\n```\n\n"
                f"## Detailed Source File Markdown Summary\n{relevant_md}\n\n"
                f"Instructions:\n"
                f"1. Read files as needed; write `plan.md`, `analysis.py`, and `tests/test_analysis.py` using `write_file`.\n"
                f"2. `analysis.py` MUST read source file(s) from `os.environ['SOURCE_INPUT_DIR']`, verify BOTH `parent_claim` "
                f"and every item in `children_claims` (when non-empty), and write `result.json` + `evidence_bundle.json` "
                f"in `.` with `verified` (bool), `computed_value`, `reported_value`, `parent_verified`, and `children_results`.\n"
                f"3. Execute `python analysis.py` and `python -m pytest tests/test_analysis.py -q` via `shell`. Fix any errors before finishing."
            )
            h_res: HarnessRunResult = run_harness_task(
                run_id=run_id,
                stage="rules",
                agent_id=f"RuleHarness-{claim_id}",
                goal=goal,
                workspace_dir=ws_dir,
                readonly_dirs=readonly_dirs,
                env_vars={
                    "SOURCE_INPUT_DIR": str(src_parent),
                    "RUN_ID": run_id,
                    "CLAIM_ID": claim_id,
                },
                developer_instructions=rule_system_prompt,
                max_turns=24,
            )
            tool_history = h_res.tool_history
        else:
            # Deterministic real-Python script creation using discovered source coordinates
            primary_fn = Path(matched_src_path).name if matched_src_path else "source.xlsx"
            vp = (claim.get("evidence_hint") or {}).get("verification_plan") or {}
            ds_match = next(
                (
                    d for d in sk_datasets
                    if d.get("source_filename") == primary_fn and d.get("is_data", True)
                ),
                next((d for d in sk_datasets if d.get("source_filename") == primary_fn), {}),
            )
            sheet_name = vp.get("sheet") or ds_match.get("sheet_or_table") or primary_fn
            header_idx = (
                vp.get("header_row_index")
                if vp.get("header_row_index") is not None
                else (ds_match.get("header_row") or 0)
            )
            dedup_key = vp.get("dedup_key") or (
                (ds_match.get("candidate_key_columns") or [None])[0]
                or ((ds_match.get("data_columns") or ["Case Number"])[0])
            )
            _write_deterministic_claim_files(
                ws_dir=ws_dir,
                claim=claim,
                primary_source_file=primary_fn,
                sheet_name=sheet_name,
                header_row_index=int(header_idx),
                dedup_key=dedup_key,
            )

        # Deterministic post-execution verification in sandbox
        exec_result: dict[str, Any]
        if (ws_dir / "analysis.py").exists():
            exec_result = default_sandbox.execute(
                run_id=run_id,
                claim_id=claim_id,
                script_path="analysis.py",
                workspace_dir=ws_dir,
                source_input_dir=src_parent,
            )
        else:
            exec_result = {
                "run_id": run_id,
                "claim_id": claim_id,
                "script_path": "analysis.py",
                "exit_code": -1,
                "stdout": "",
                "stderr": "Harness finished without creating analysis.py",
                "status": "error",
                "result_data": None,
            }

        # Enforce source immutability strictly
        after_hashes = _snapshot_hashes(source_paths)
        if baseline_hashes != after_hashes:
            raise RuntimeError("SECURITY VIOLATION: source file SHA-256 changed during Stage 2")

        (ws_dir / "execution.json").write_text(json.dumps(exec_result, indent=2), encoding="utf-8")

        result_data = exec_result.get("result_data")
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if exec_result.get("exit_code") == 0 and isinstance(result_data, dict):
            # Re-verify boolean or compute from values cleanly
            computed_val = result_data.get("computed_value")
            reported_val = claim.get("reported_value")
            parent_ok = (
                bool(result_data["parent_verified"])
                if "parent_verified" in result_data
                else _values_match(reported_val, computed_val)
            )
            children_results = result_data.get("children_results") or []
            children_ok = all(bool(cr.get("verified")) for cr in children_results) if children_results else True
            is_verified = bool(result_data.get("verified", parent_ok and children_ok))

            # Propagate computed results onto each ChildClaim record for UI display
            existing_children = claim.get("children_claims") or []
            cr_by_id = {cr.get("child_claim_id"): cr for cr in children_results if isinstance(cr, dict)}
            for c_idx, ch in enumerate(existing_children):
                cid = ch.get("child_claim_id", "")
                matched_cr = cr_by_id.get(cid) or (children_results[c_idx] if c_idx < len(children_results) else None)
                if isinstance(matched_cr, dict):
                    ch["verified"] = bool(matched_cr.get("verified"))
                    ch["computed_value"] = matched_cr.get("computed_value")
                    ch["verification_notes"] = matched_cr.get("notes")

            claim["children_claims"] = existing_children
            new_status = ClaimStatus.verified.value if is_verified else ClaimStatus.discrepancy.value
            if is_verified:
                verified_count += 1
            else:
                discrepancy_count += 1

            vr = VerificationResult(
                verified=is_verified,
                status="verified" if is_verified else "discrepancy",
                parent_computed_value=computed_val,
                parent_reported_value=reported_val,
                children_results=children_results,
                discrepancy_summary=None if is_verified else f"Computed {computed_val} vs reported {reported_val}",
                script_path=f"stage_2_rules/claims/{claim_id}/analysis.py",
                verified_at=now_iso,
            )
        else:
            failed_count += 1
            new_status = ClaimStatus.failed.value
            vr = VerificationResult(
                verified=False,
                status="failed",
                parent_computed_value=None,
                parent_reported_value=claim.get("reported_value"),
                children_results=[],
                discrepancy_summary=exec_result.get("stderr") or "Execution failed without result.json",
                script_path=f"stage_2_rules/claims/{claim_id}/analysis.py",
                verified_at=now_iso,
            )

        claim["status"] = new_status
        claim["verification_result"] = vr.model_dump(mode="json")

        # Publish artifacts for this claim
        result_art_id: str | None = None
        artifact_specs = [
            ("plan.md", "text/markdown"),
            ("analysis.py", "text/x-python"),
            ("result.json", "application/json"),
            ("evidence_bundle.json", "application/json"),
            ("execution.json", "application/json"),
            ("tests/test_analysis.py", "text/x-python"),
        ]
        for rel_name, media_type in artifact_specs:
            p = ws_dir / rel_name
            if p.exists():
                art = _publish_claim_artifact(run_id, claim_id, rel_name, media_type, p.read_text(encoding="utf-8"))
                claim_artifact_hashes[art["logical_path"]] = art["sha256"]
                if rel_name == "result.json":
                    result_art_id = art["artifact_id"]

        if tool_history:
            hist_body = "\n".join(json.dumps(e) for e in tool_history)
            art = _publish_claim_artifact(run_id, claim_id, "tool_history.jsonl", "application/x-ndjson", hist_body)
            claim_artifact_hashes[art["logical_path"]] = art["sha256"]

        if result_art_id:
            claim["verification_result"]["result_artifact_id"] = result_art_id

        updated_claim = default_claim_repo.save_claim(run_id, claim)
        default_broker.emit_claim_update(run_id, updated_claim)
        default_broker.emit_activity(
            run_id=run_id,
            stage="rules",
            title=f"{claim_id} -> {new_status.upper()}",
            detail=(
                f"Verified: computed {vr.parent_computed_value} == reported {vr.parent_reported_value}"
                if vr.verified
                else (vr.discrepancy_summary or "Discrepancy or error during verification")
            )[:220],
            kind="success" if vr.verified else "warning",
            status="done" if vr.verified else "warning",
        )
        progress = int(10 + 85 * (idx / total_claims))
        default_broker.emit_stage_update(run_id, "rules", "running", progress=progress)

    # Freeze Stage 2 manifest & transition to RULES_AWAITING_REVIEW
    manifest_payload = json.dumps(
        {
            "run_id": run_id,
            "stage_1_manifest_hash": expected_stage_1_manifest_hash,
            "verified_count": verified_count,
            "discrepancy_count": discrepancy_count,
            "failed_count": failed_count,
            "artifact_hashes": claim_artifact_hashes,
        },
        indent=2,
    )
    manifest_store = default_storage.put_derived(
        tenant_id="default",
        run_id=run_id,
        logical_path="stage_2_rules/manifest.json",
        body=manifest_payload,
    )
    stage_2_hash = hashlib.sha256(
        f"{expected_stage_1_manifest_hash}:{manifest_store['sha256']}".encode()
    ).hexdigest()
    default_run_repo.set_manifest_hash(run_id, "rules", stage_2_hash)

    latest = default_run_repo.get_run(run_id)
    default_run_repo.transition(
        run_id=run_id,
        expected_version=latest["version"],
        new_state=RunState.RULES_AWAITING_REVIEW,
        active_stage=None,
    )

    default_broker.emit_stage_update(run_id, "rules", "review", progress=100)
    default_broker.emit_activity(
        run_id=run_id,
        stage="rules",
        title="Stage 2 complete — awaiting review",
        detail=f"{verified_count} verified · {discrepancy_count} discrepancy · {failed_count} failed",
        kind="gate",
        status="warning",
    )
    default_broker.emit_run_finished(
        run_id,
        "rules",
        {
            "verified_count": verified_count,
            "discrepancy_count": discrepancy_count,
            "failed_count": failed_count,
        },
    )

    return {
        "run_id": run_id,
        "status": RunState.RULES_AWAITING_REVIEW.value,
        "stage_2_manifest_hash": stage_2_hash,
        "verified_count": verified_count,
        "discrepancy_count": discrepancy_count,
        "failed_count": failed_count,
    }
