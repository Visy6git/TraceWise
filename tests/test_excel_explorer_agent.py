from pathlib import Path
from openpyxl import Workbook
import app.services.excel_explorer_agent as ea
from app.services.llm_client import parse_all_xml_tool_calls


def _build_sample_xlsx(path: Path, n_rows: int = 12):
    wb = Workbook()
    ws = wb.active
    ws.title = "Drug Events"
    ws.append(["Report Banner: Demo Safety Export"])
    ws.append(["Case Number", "Patient ID", "Event PT (Primary Path)", "Primary Source", "Initial/Follow-up", "Initial Approval Date"])
    pts = ["Somnolence", "Hallucination", "Dystonia", "Somnolence"]
    sources = ["Spontaneous", "Report from other studies"]
    for i in range(n_rows):
        ws.append([
            f"CASE-{(i // 2) + 1:04d}",
            f"PAT-{i + 1:05d}",
            pts[i % len(pts)],
            sources[i % 2],
            "Initial" if i % 3 != 0 else "Follow-up",
            f"20250{(i % 6) + 1}15",
        ])
    wb.save(path)


def test_100_line_preview_and_isolated_sandbox_tools(tmp_path):
    xlsx = tmp_path / "events_sample.xlsx"
    _build_sample_xlsx(xlsx, n_rows=120)

    preview = ea.extract_excel_100_line_preview(xlsx, max_lines=100)
    assert "FILE: events_sample.xlsx" in preview
    assert "Event PT (Primary Path)" in preview
    row_lines = [ln for ln in preview.splitlines() if ln.startswith("Row ")]
    assert len(row_lines) == 100

    sandbox = ea.IsolatedExcelSandbox(tmp_path / "sandbox_1", xlsx)
    assert (sandbox.agent_dir / "events_sample.xlsx").is_file()

    # Read-only source protection & path traversal protection
    assert sandbox.write_file("events_sample.xlsx", "hack")["ok"] is False
    try:
        sandbox.write_file("../escape.py", "print(1)")
        assert False, "Expected path escape rejection"
    except ValueError:
        pass

    # Write, edit, read, and execute Python in isolated terminal
    w = sandbox.write_file("analysis.py", "import pandas as pd\ndf = pd.read_excel('events_sample.xlsx', header=1)\nprint('ROWS', len(df))\n")
    assert w["ok"] is True
    e = sandbox.edit_file("analysis.py", "print('ROWS', len(df))", "print('ROWS', len(df), 'CASES', df['Case Number'].nunique())")
    assert e["ok"] is True
    r = sandbox.read_file("analysis.py")
    assert "CASES" in r["content"]
    t = sandbox.run_terminal("python analysis.py")
    assert t["ok"] is True and t["exit_code"] == 0
    assert "ROWS 120 CASES 60" in t["stdout"]


def test_parallel_excel_explorers_emit_agui_and_export_md_and_analysis_py(tmp_path, monkeypatch):
    f1 = tmp_path / "01_events.xlsx"
    f2 = tmp_path / "02_cases.xlsx"
    _build_sample_xlsx(f1, n_rows=10)
    _build_sample_xlsx(f2, n_rows=8)
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    turn_counter: dict[str, int] = {}

    def fake_invoke_agent_turn(messages, tools, **kwargs):
        # Identify which file this agent is working on from the initial user message
        u0 = messages[1]["content"]
        fname = "01_events.xlsx" if "01_events.xlsx" in u0 else "02_cases.xlsx"
        stem = fname.replace(".xlsx", "")
        turn_counter[fname] = turn_counter.get(fname, 0) + 1
        t = turn_counter[fname]

        if t == 1:
            code = (
                f'"""Navigation & analysis helper for {fname} (header at row 2)."""\n'
                f'import pandas as pd\n'
                f'df = pd.read_excel({fname!r}, header=1)\n'
                f'print("ROWS:", len(df), "DISTINCT_CASES:", df["Case Number"].nunique())\n'
                f'print("PTS:", df["Event PT (Primary Path)"].value_counts().to_dict())\n'
            )
            return {
                "text": "Writing analysis.py",
                "tool_calls": [
                    {"name": "write_file", "arguments": {"filename": "analysis.py", "content": code}},
                    {"name": "run_terminal", "arguments": {"command": "python analysis.py"}},
                ],
            }
        md = (
            f"# Detailed Analysis — {fname}\n\n"
            f"- Distinct Case IDs verified via `analysis.py`.\n"
            f"- `Event PT (Primary Path)` defined-set values counted.\n"
        )
        return {
            "text": "Writing markdown report and completing",
            "tool_calls": [
                {"name": "write_file", "arguments": {"filename": f"{stem}.md", "content": md}},
                {"name": "complete_exploration", "arguments": {"md_file": f"{stem}.md", "analysis_py_file": "analysis.py", "summary_notes": "Done"}},
            ],
        }

    monkeypatch.setattr(ea, "invoke_agent_turn", fake_invoke_agent_turn)
    monkeypatch.setattr(
        ea,
        "llm_status_info",
        lambda: {"llm_enabled": True, "llm_provider": "lmstudio", "llm_model_id": "prism-ml/bonsai-27b"},
    )

    events = []
    profiles = ea.run_parallel_excel_explorers(
        [f1, f2],
        work_dir,
        emitter=lambda et, payload: events.append((et, payload)),
    )

    assert [p["filename"] for p in profiles] == ["01_events.xlsx", "02_cases.xlsx"]
    assert (work_dir / "01_events.md").is_file()
    assert (work_dir / "01_events_analysis.py").is_file()
    assert (work_dir / "02_cases.md").is_file()
    assert (work_dir / "02_cases_analysis.py").is_file()

    file_statuses = [
        (p["value"]["filename"], p["value"]["status"])
        for et, p in events
        if et == "CUSTOM" and p.get("name") == "source.file_status"
    ]
    for fn in ("01_events.xlsx", "02_cases.xlsx"):
        statuses = [st for name, st in file_statuses if name == fn]
        assert "reading_context" in statuses
        assert "running_terminal" in statuses
        assert statuses[-1] == "completed"


def test_parse_all_xml_tool_calls_preserves_python_indentation():
    xml = (
        "<tool_call>\n"
        "<function=write_file>\n"
        "<parameter=filename>\nanalysis.py\n</parameter>\n"
        "<parameter=content>\ndef load():\n    return 42\n</parameter>\n"
        "</function>\n"
        "</tool_call>"
    )
    calls = parse_all_xml_tool_calls(xml)
    assert len(calls) == 1
    assert calls[0]["name"] == "write_file"
    assert calls[0]["arguments"]["filename"] == "analysis.py"
    assert calls[0]["arguments"]["content"] == "def load():\n    return 42"
