from pathlib import Path
import pytest
from app.services.sandbox import AgentSandbox


def test_sandbox_lifecycle(tmp_path):
    run_dir = tmp_path / "run_test"
    input_dir = run_dir / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "protected_source.xlsx").write_text("dummy", encoding="utf-8")

    box = AgentSandbox(run_dir, input_dir)

    # 1. Write Python script
    code = (
        "import os\n"
        "input_dir = os.environ.get('SOURCE_INPUT_DIR')\n"
        "assert input_dir and os.path.exists(input_dir)\n"
        "print('Sandbox Python execution successful!')\n"
        "with open('output.txt', 'w') as f: f.write('computed_metric=42')\n"
    )
    box.write_file("worker.py", code)
    assert len(box.list_files()) == 1

    # 2. Execute script
    res = box.execute_python("worker.py")
    assert res.exit_code == 0
    assert "Sandbox Python execution successful!" in res.stdout
    assert "output.txt" in res.output_files

    # 3. Read generated output
    assert box.read_file("output.txt") == "computed_metric=42"

    # 4. Forbid deleting input file
    with pytest.raises(PermissionError):
        box.delete_file("protected_source.xlsx")

    # 5. Delete generated file
    del_res = box.delete_file("output.txt")
    assert del_res["status"] == "deleted"

