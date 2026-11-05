import shutil
from pathlib import Path
from app.services.sample_pbrer import generate_pbrer_sample_bundle
from app.services.agents import MultiAgentOrchestrator


def test_full_agent_autonomy_flow():
    base_dir = Path("runtime/test_run_env")
    shutil.rmtree(base_dir, ignore_errors=True)
    input_dir = base_dir / "input"
    input_dir.mkdir(parents=True)
    work_dir = base_dir / "work"
    work_dir.mkdir(parents=True)

    try:
        files = generate_pbrer_sample_bundle(input_dir)

        manifest = [
            {"role": "target", "filename": files["target"].name, "stored_name": files["target"].name, "sha256": "abc", "size": 100},
            {"role": "source", "filename": files["clinical"].name, "stored_name": files["clinical"].name, "sha256": "def", "size": 100},
            {"role": "source", "filename": files["sales"].name, "stored_name": files["sales"].name, "sha256": "ghi", "size": 100},
            {"role": "source", "filename": files["icsr"].name, "stored_name": files["icsr"].name, "sha256": "jkl", "size": 100},
            {"role": "source", "filename": files["signals"].name, "stored_name": files["signals"].name, "sha256": "mno", "size": 100},
        ]

        target_outline = [
            {"id": "sec-5.1", "title": "5.1 Cumulative Subject Exposure in Clinical Trials", "source": "Target DOCX"},
            {"id": "sec-5.2", "title": "5.2 Cumulative and Interval Patient Exposure from Marketing Experience", "source": "Target DOCX"},
            {"id": "sec-7.2", "title": "7.2 Tabulations of Serious Adverse Reactions from Post-Marketing Sources", "source": "Target DOCX"},
            {"id": "sec-9.1", "title": "9.1 Summary of Safety Signals", "source": "Target DOCX"},
        ]

        orch = MultiAgentOrchestrator("test_run_env", base_dir, input_dir, manifest, target_outline)
        orch.run_autonomous_investigation()

        # Check section 5.1
        assert orch.mappings["sec-5.1"].status == "rules_compiled"
        assert len(orch.mappings["sec-5.1"].rules) > 0
        assert orch.mappings["sec-5.1"].computed_metrics.get("total_cumulative_subjects") == 12450

        # Check section 5.2
        assert orch.mappings["sec-5.2"].status == "rules_compiled"
        assert orch.mappings["sec-5.2"].computed_metrics.get("interval_patient_years_2024") == 384500

        # Check section 7.2
        assert orch.mappings["sec-7.2"].status == "rules_compiled"
        assert orch.mappings["sec-7.2"].computed_metrics.get("total_serious_icsrs") == 342

        # Check section 9.1
        assert orch.mappings["sec-9.1"].status == "rules_compiled"
        assert orch.mappings["sec-9.1"].computed_metrics.get("total_signals") == 3

        # Check sandbox files
        sandbox_files = orch.sandbox.list_files()
        file_names = [f["name"] for f in sandbox_files]
        assert "pbrer_sec5_exposure_calc.py" in file_names
        assert "pbrer_sec7_icsr_safety_metrics.py" in file_names
        assert "pbrer_sec9_signal_evaluator.py" in file_names
        assert "complete_traceability_matrix.json" in file_names

        # User note guidance
        orch.add_user_note("sec-7.2", "Auditor note: Reconfirm fatal outcome cases.")
        assert len(orch.mappings["sec-7.2"].user_notes) == 1
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)
