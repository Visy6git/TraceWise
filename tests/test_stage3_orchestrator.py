from __future__ import annotations

import json
from pathlib import Path

from app.control_plane.run_state import RunState
from app.harness.runner import HarnessRunResult
from app.stages.stage_3_understanding import orchestrator


def test_stage3_harness_gets_bounded_repair_for_missing_files(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    readonly_inputs = tmp_path / "read_only_inputs"
    readonly_inputs.mkdir()
    (workspace / "blueprint.json").write_text(json.dumps({
        "claims": [{"claim_id": "CLM-1"}],
        "section_structure": [{"block_id": "section-16-3"}],
        "status": "draft",
        "validation": {},
    }), encoding="utf-8")

    calls = []

    def fake_run_harness_task(**kwargs):
        calls.append(kwargs)
        if "Continue the existing Stage 3 authoring attempt" in kwargs["goal"]:
            for name in (
                "section_model.json", "claim_catalog.json", "source_contracts.json",
                "retrieval_policies.json", "transformation_graph.json",
                "narrative_templates.json", "render_spec.json", "schema_drift_policy.json",
            ):
                (workspace / name).write_text("{}", encoding="utf-8")
            (workspace / "reproduce_section.py").write_text(
                "def main():\n    raise RuntimeError('Unresolved source mapping')\n",
                encoding="utf-8",
            )
            tests = workspace / "tests"
            tests.mkdir()
            (tests / "test_reproduction_contract.py").write_text(
                "def test_contract():\n    assert True\n", encoding="utf-8",
            )
            (workspace / "README.md").write_text("Candidate contract", encoding="utf-8")
        return HarnessRunResult(
            success=True,
            final_response="",
            turns=2,
            tool_calls_count=4,
        )

    monkeypatch.setattr(orchestrator, "run_harness_task", fake_run_harness_task)
    result, validation, attempts = orchestrator._run_harness_with_package_repairs(
        run_id="run-stage3-repair",
        blueprint_id="bp-stage3-repair",
        workspace=workspace,
        readonly_inputs=readonly_inputs,
        env_vars={"TRACEWISE_STAGE": "understanding"},
        goal="Build the Stage 3 candidate.",
    )

    assert len(calls) == 2
    assert "reproduce_section.py" in calls[1]["goal"]
    assert (workspace / "reproduce_section.py").is_file()
    assert validation["missing_files"] == []
    assert validation["status"] == "blocked"
    assert validation["issues"] == ["No isolated reproduction test evidence is recorded."]
    assert result.success
    assert [attempt["turns"] for attempt in attempts] == [2, 2]


def test_failed_stage3_authoring_is_not_marked_awaiting_review(isolated_env, monkeypatch):
    run_repo = isolated_env["run_repo"]
    run_id = "run-stage3-bedrock-failure"
    run_repo.create_run(
        run_id=run_id,
        run_name="Stage 3 Bedrock failure",
        target_object_id="target-1",
        source_object_ids=["source-1"],
        input_manifest_hash="input-hash-12345678",
    )
    run_repo.set_manifest_hash(run_id, "claims", "stage-1-manifest-hash")
    run_repo.set_manifest_hash(run_id, "rules", "stage-2-manifest-hash")
    for next_state, stage in (
        (RunState.CLAIMS_RUNNING, "claims"),
        (RunState.CLAIMS_AWAITING_REVIEW, "claims"),
        (RunState.CLAIMS_APPROVED, None),
        (RunState.RULES_RUNNING, "rules"),
        (RunState.RULES_AWAITING_REVIEW, "rules"),
        (RunState.RULES_APPROVED, None),
        (RunState.EVALUATION_RUNNING, "evaluation"),
    ):
        run = run_repo.get_run(run_id)
        run_repo.transition(run_id, run["version"], next_state, active_stage=stage)

    storage = isolated_env["storage"]
    run_dir = storage.run_dir(run_id)
    (run_dir / "stage_1_claims").mkdir()
    (run_dir / "stage_2_rules").mkdir()
    monkeypatch.setattr(orchestrator, "default_run_repo", run_repo)
    monkeypatch.setattr(orchestrator, "default_storage", storage)
    monkeypatch.setattr(orchestrator, "default_artifact_repo", isolated_env["artifact_repo"])
    monkeypatch.setattr(orchestrator, "default_broker", isolated_env["broker"])
    monkeypatch.setattr(
        orchestrator,
        "_run_harness_with_package_repairs",
        lambda **_kwargs: (
            HarnessRunResult(
                success=False,
                final_response="",
                turns=1,
                tool_calls_count=0,
                error="Bedrock credentials expired",
            ),
            {
                "status": "blocked",
                "missing_files": ["reproduce_section.py"],
                "issues": [],
            },
            [{"attempt": 1, "success": False, "turns": 1, "tool_calls": 0}],
        ),
    )
    import app.services.blueprint_repository as bp_module
    monkeypatch.setattr(bp_module, "default_blueprint_repo", isolated_env["blueprint_repo"])

    result = orchestrator.run_understanding_stage(run_id, "stage-2-manifest-hash")

    run = run_repo.get_run(run_id)
    assert result["status"] == "failed"
    assert run["status"] == RunState.FAILED
    assert run["active_stage"] == "evaluation"
    assert result["error"] == "Bedrock credentials expired"
