import threading
import time
from pathlib import Path
from docx import Document
from fastapi.testclient import TestClient
import app.main as main_mod
from app.services.pause_controller import PauseController
import app.services.template_agent as ta
import app.services.excel_explorer_agent as eea


def test_pause_controller_basics():
    pc = PauseController()
    assert pc.is_paused is False
    assert pc.wait_if_paused(timeout=0.01) is True

    pc.pause()
    assert pc.is_paused is True
    # Should block while paused (returning False on timeout)
    assert pc.wait_if_paused(timeout=0.05) is False

    # Resume from background thread
    def _unpause_later():
        time.sleep(0.05)
        pc.resume()

    t = threading.Thread(target=_unpause_later)
    t.start()
    unblocked = pc.wait_if_paused(timeout=1.0)
    t.join()
    assert unblocked is True
    assert pc.is_paused is False


def test_api_template_run_pause_and_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(main_mod.settings, "workspace_root", tmp_path)
    monkeypatch.setattr(main_mod.settings, "database_path", tmp_path / "test.sqlite3")
    main_mod.db.init_db()
    main_mod.RUNS.clear()

    pc = PauseController()
    main_mod.RUNS["run_test_1"] = {
        "run_id": "run_test_1",
        "tenant_id": "demo-tenant",
        "run_type": "template",
        "name": "Test Template",
        "status": "running",
        "pause_controller": pc,
        "input_dir_rel": "demo-tenant/template_runs/run_test_1/input",
        "work_dir_rel": "demo-tenant/template_runs/run_test_1/work",
        "events": [],
    }

    client = TestClient(main_mod.app)

    # 1. Nonexistent run
    bad_res = client.post("/api/template-runs/nonexistent/pause")
    assert bad_res.status_code == 404

    # 2. Pause active run
    pause_res = client.post("/api/template-runs/run_test_1/pause")
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "paused"
    assert pc.is_paused is True
    assert main_mod.RUNS["run_test_1"]["status"] == "paused"

    # Pausing again while paused -> 409
    dup_pause = client.post("/api/template-runs/run_test_1/pause")
    assert dup_pause.status_code == 409

    # GET run reports is_paused=True
    get_res = client.get("/api/template-runs/run_test_1")
    assert get_res.json()["status"] == "paused"
    assert get_res.json()["is_paused"] is True

    # 3. Resume paused run
    resume_res = client.post("/api/template-runs/run_test_1/resume")
    assert resume_res.status_code == 200
    assert resume_res.json()["status"] == "running"
    assert pc.is_paused is False
    assert main_mod.RUNS["run_test_1"]["status"] == "running"

    # Resuming again while running -> 409
    dup_resume = client.post("/api/template-runs/run_test_1/resume")
    assert dup_resume.status_code == 409


def test_api_generator_run_pause_and_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(main_mod.settings, "workspace_root", tmp_path)
    monkeypatch.setattr(main_mod.settings, "database_path", tmp_path / "test.sqlite3")
    main_mod.db.init_db()
    main_mod.RUNS.clear()

    pc = PauseController()
    main_mod.RUNS["run_gen_1"] = {
        "run_id": "run_gen_1",
        "tenant_id": "demo-tenant",
        "run_type": "generator",
        "name": "Test Generator",
        "status": "running",
        "pause_controller": pc,
        "input_dir_rel": "demo-tenant/generator_runs/run_gen_1/input",
        "work_dir_rel": "demo-tenant/generator_runs/run_gen_1/work",
        "events": [],
    }

    client = TestClient(main_mod.app)

    # 1. Nonexistent generator run
    bad_res = client.post("/api/generator-runs/nonexistent/pause")
    assert bad_res.status_code == 404

    # 2. Pause generator run
    pause_res = client.post("/api/generator-runs/run_gen_1/pause")
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "paused"
    assert pc.is_paused is True

    get_res = client.get("/api/generator-runs/run_gen_1")
    assert get_res.json()["status"] == "paused"
    assert get_res.json()["is_paused"] is True

    # 3. Resume generator run
    resume_res = client.post("/api/generator-runs/run_gen_1/resume")
    assert resume_res.status_code == 200
    assert resume_res.json()["status"] == "running"
    assert pc.is_paused is False


def test_pipeline_honors_cooperative_pause(tmp_path, monkeypatch):
    doc_path = tmp_path / "simple.docx"
    doc = Document()
    doc.add_heading("16.3 Evaluation of risks and new information", level=1)
    doc.add_heading("Safety Topic 1", level=3)
    t = doc.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Topic count"
    t.cell(0, 1).text = "10"
    t.cell(1, 0).text = "Conclusion"
    t.cell(1, 1).text = "Ok"
    doc.save(doc_path)

    pc = PauseController()
    pause_check_called = []

    def tracking_pause_check():
        pause_check_called.append(True)
        pc.wait_if_paused()

    # Pre-pause the controller
    pc.pause()

    # Stub out the tool calls so pipeline runs fast
    def fake_invoke_tool_call(system_prompt, user_prompt, tool_name, tool_description, input_model, **kwargs):
        if tool_name == "register_table_blueprint":
            return ta.BlueprintTableSpec(
                table_id="t1",
                topic_heading="Safety Topic 1",
                fields=[
                    ta.BlueprintFieldSpec(
                        field_label="Topic count",
                        key="topic_total",
                        type="count",
                        generic_placeholder="{{count}}",
                        source_intent="Count",
                        required=True,
                        row_index=0,
                        cell_index=1,
                    )
                ],
            )
        if tool_name == "publish_master_knowledge":
            return ta.MasterMarkdownResponse(
                master_md="# Guide",
                reference_summaries=[
                    ta.ReferenceTableSummary(
                        table_id="t1",
                        topic_heading="Safety Topic 1",
                        why_selected="Example",
                        structure_summary="Summary",
                        example_fields=["Field 1"],
                    )
                ],
            )
        raise AssertionError(tool_name)

    monkeypatch.setattr(ta, "invoke_tool_call", fake_invoke_tool_call)
    monkeypatch.setattr(ta, "llm_status_info", lambda: {"llm_enabled": True, "llm_provider": "lmstudio"})

    # Launch pipeline in a thread — it must block on tracking_pause_check()!
    pipeline_result = {}

    def _run():
        res = ta.run_agui_template_pipeline(
            run_id="run_pause_test",
            tenant_id="tenant-1",
            run_name="Pause Test",
            docx_paths=[doc_path],
            work_dir=tmp_path,
            pause_check=tracking_pause_check,
        )
        pipeline_result["done"] = True
        pipeline_result["res"] = res

    worker_thread = threading.Thread(target=_run)
    worker_thread.start()

    # Give worker time to start and hit the pause checkpoint
    time.sleep(0.1)
    assert len(pause_check_called) >= 1
    assert "done" not in pipeline_result  # Must be blocked!

    # Resume the controller
    pc.resume()
    worker_thread.join(timeout=2.0)
    assert pipeline_result.get("done") is True
