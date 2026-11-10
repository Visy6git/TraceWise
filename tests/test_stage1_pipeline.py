"""Stage 1 pipeline tests: per-file harness exploration -> Master Summary .md -> subsection Strands claims."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.control_plane.run_state import RunState
from app.stages.stage_1_claims.orchestrator import run_claims_stage
from app.stages.stage_1_claims.source_explorer import explore_all_sources_with_harness
from tests.conftest import create_synthetic_pbrer_dataset


def test_stage1_per_file_exploration_and_subsection_claims(isolated_env, tmp_path: Path):
    storage = isolated_env["storage"]
    run_repo = isolated_env["run_repo"]
    claim_repo = isolated_env["claim_repo"]
    artifact_repo = isolated_env["artifact_repo"]

    doc_path, source_paths = create_synthetic_pbrer_dataset(tmp_path / "inputs")
    h = hashlib.sha256()
    h.update(doc_path.read_bytes())
    for sp in source_paths:
        h.update(sp.read_bytes())
    manifest_hash = h.hexdigest()

    run = run_repo.create_run(
        run_id="run-stage1-test",
        run_name="Stage 1 Synthetic Run",
        target_object_id=str(doc_path),
        source_object_ids=[str(sp) for sp in source_paths],
        input_manifest_hash=manifest_hash,
    )
    run_repo.transition(
        run_id=run["run_id"],
        expected_version=run["version"],
        new_state=RunState.CLAIMS_RUNNING,
        active_stage="claims",
    )

    result = run_claims_stage(run["run_id"], manifest_hash)
    assert result["status"] == RunState.CLAIMS_AWAITING_REVIEW.value
    assert result["claim_count"] == 2

    # Verify per-file Python navigation modules + per-file .md + master_source_summary.md exist
    artifacts = artifact_repo.list_artifacts(run["run_id"])
    paths = [a["logical_path"] for a in artifacts]
    assert "stage_1_claims/master_source_summary.md" in paths
    assert "stage_1_claims/sources/src_01_01_hepatic_csmr_explore.py" in paths
    assert "stage_1_claims/sources/src_01_01_hepatic_csmr.md" in paths
    assert "stage_1_claims/sources/src_02_02_severe_skin_csmr_explore.py" in paths
    assert "stage_1_claims/sources/src_02_02_severe_skin_csmr.md" in paths

    # Verify generated .py file embeds columns, types & unique values natively
    py_content = storage.read_text(
        f"default/{run['run_id']}/stage_1_claims/sources/src_01_01_hepatic_csmr_explore.py"
    )
    assert "SOURCE_CATALOG" in py_content
    assert "Case Number" in py_content
    assert "Spontaneous" in py_content
    assert "'header_row_index': 3" in py_content

    # Verify master_source_summary.md mentions all files & categorical uniques
    master_md = storage.read_text(f"default/{run['run_id']}/stage_1_claims/master_source_summary.md")
    assert "01_Hepatic_CSMR.xlsx" in master_md
    assert "02_Severe_skin_CSMR.csv" in master_md
    assert "Spontaneous" in master_md

    # Verify hierarchical claims persisted (both parent+children and empty children_claims=[])
    claims = claim_repo.list_claims(run["run_id"])
    assert len(claims) == 2

    clm_hepatic = next(c for c in claims if c["section_number"] == "16.3.1.1")
    assert clm_hepatic["reported_value"] == "235"
    assert clm_hepatic["denominator"] == "500"
    assert "hepatic disorders" in clm_hepatic["search_criteria"].lower()
    assert clm_hepatic["source_document_mapped"] == ["01_Hepatic_CSMR.xlsx"]
    assert len(clm_hepatic["children_claims"]) >= 3
    child_rels = {ch["relationship"] for ch in clm_hepatic["children_claims"]}
    assert "serious_subset" in child_rels
    assert "fatal_subset" in child_rels
    assert "source_split" in child_rels

    clm_skin = next(c for c in claims if c["section_number"] == "16.3.1.2")
    assert clm_skin["reported_value"] == "12"
    assert clm_skin["children_claims"] == []
    assert clm_skin["source_document_mapped"] == ["02_Severe_skin_CSMR.csv"]


def test_stage1_harness_live_exploration_invocation(isolated_env, tmp_path: Path, monkeypatch):
    """Verify explore_all_sources_with_harness calls run_harness_task once per source file."""
    run_repo = isolated_env["run_repo"]
    doc_path, source_paths = create_synthetic_pbrer_dataset(tmp_path / "inputs_live")
    run_repo.create_run(
        run_id="run-harness-loop",
        run_name="Per File Loop Test",
        target_object_id=str(doc_path),
        source_object_ids=[str(sp) for sp in source_paths],
        input_manifest_hash="b" * 32,
    )

    seen_goals: list[str] = []

    def fake_run_harness(**kwargs):
        seen_goals.append(kwargs["goal"])
        ws = Path(kwargs["workspace_dir"])
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "explore_source.py").write_text("SOURCE_CATALOG = {'Sheet1': {}}\n", encoding="utf-8")
        (ws / "summary.md").write_text("# Custom Harness MD Summary\n", encoding="utf-8")
        from app.harness.runner import HarnessRunResult

        return HarnessRunResult(
            success=True,
            final_response="Done",
            turns=2,
            tool_calls_count=3,
            files_written=["explore_source.py", "summary.md"],
        )

    import app.stages.stage_1_claims.source_explorer as se_mod

    monkeypatch.setattr(se_mod, "run_harness_task", fake_run_harness)
    res = explore_all_sources_with_harness(
        run_id="run-harness-loop",
        source_paths=[str(sp) for sp in source_paths],
        live_harness=True,
    )

    assert len(seen_goals) == len(source_paths)
    assert "01_Hepatic_CSMR.xlsx" in seen_goals[0]
    assert "02_Severe_skin_CSMR.csv" in seen_goals[1]
    assert "FIRST 100 rows" in seen_goals[0]
    assert "Master Summary of Source Documents" in res["master_summary_md"]

