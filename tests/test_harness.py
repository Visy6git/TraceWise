"""Tests for the integrated TraceWise coding-agent harness (app/harness/)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest

from app.harness.config import ApprovalPolicy, HarnessConfig, ShellEnvironmentPolicy
from app.harness.events import StreamEventType
from app.harness.llm_client import LLMClient
from app.harness.paths import strip_extended_prefix
from app.harness.runner import run_harness_task_async
from app.harness.tools.base import ToolInvocation
from app.harness.tools.edit_file import EditTool
from app.harness.tools.read_file import ReadFileTool
from app.harness.tools.shell import ShellTool
from app.harness.tools.write_file import WriteFileTool


def test_llm_client_parses_non_stream_tool_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Calling write_file",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "write_file",
                                        "arguments": '{"path":"hello.py","content":"print(1)"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    import asyncio

    async def _run():
        cfg = HarnessConfig(provider="lmstudio", base_url="http://mock.local/v1")
        client = LLMClient(cfg, transport=httpx.MockTransport(handler))
        events = []
        async for ev in client.chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "write_file", "description": "write", "parameters": {"type": "object", "properties": {}}}],
            stream=False,
        ):
            events.append(ev)
        await client.close()
        return events

    events = asyncio.run(_run())
    tc_starts = [e for e in events if e.type == StreamEventType.TOOL_CALL_START]
    tc_completes = [e for e in events if e.type == StreamEventType.TOOL_CALL_COMPLETE]
    assert len(tc_starts) == 1
    assert len(tc_completes) == 1
    assert tc_completes[0].tool_call.name == "write_file"
    assert tc_completes[0].tool_call.arguments == {"path": "hello.py", "content": "print(1)"}


def test_read_file_truncation_large_file_no_crash(tmp_path: Path):
    import asyncio

    big_file = tmp_path / "big.txt"
    big_file.write_text("\n".join(f"line {i}: " + ("x" * 120) for i in range(600)), encoding="utf-8")

    cfg = HarnessConfig(cwd=tmp_path)
    tool = ReadFileTool(cfg)
    res = asyncio.run(tool.execute(ToolInvocation(params={"path": "big.txt", "limit": 600}, cwd=tmp_path)))
    assert res.success is True
    assert "line 0:" in res.output


def test_workspace_and_readonly_confinement(tmp_path: Path):
    import asyncio

    ws = tmp_path / "ws"
    ro = tmp_path / "sources"
    ws.mkdir()
    ro.mkdir()
    ro_file = ro / "secret.csv"
    ro_file.write_text("id\n1\n", encoding="utf-8")

    cfg = HarnessConfig(cwd=ws, readonly_dirs=[ro], approval=ApprovalPolicy.AUTO)
    write_tool = WriteFileTool(cfg)
    edit_tool = EditTool(cfg)
    read_tool = ReadFileTool(cfg)

    # Reading from readonly_dirs is allowed
    r_ro = asyncio.run(read_tool.execute(ToolInvocation(params={"path": str(ro_file)}, cwd=ws)))
    assert r_ro.success is True

    # Writing outside workspace or into readonly_dirs fails
    r_escape = asyncio.run(write_tool.execute(ToolInvocation(params={"path": "../evil.txt", "content": "x"}, cwd=ws)))
    assert r_escape.success is False
    r_ro_write = asyncio.run(write_tool.execute(ToolInvocation(params={"path": str(ro_file), "content": "x"}, cwd=ws)))
    assert r_ro_write.success is False

    # Writing & editing inside workspace works (even overwrite under ApprovalPolicy.AUTO)
    r_ok = asyncio.run(write_tool.execute(ToolInvocation(params={"path": "script.py", "content": "x = 1\n"}, cwd=ws)))
    assert r_ok.success is True
    r_edit = asyncio.run(
        edit_tool.execute(
            ToolInvocation(params={"path": "script.py", "old_string": "x = 1", "new_string": "x = 2"}, cwd=ws)
        )
    )
    assert r_edit.success is True
    assert "x = 2" in (ws / "script.py").read_text(encoding="utf-8")


def test_shell_tool_venv_and_stripped_extended_path(tmp_path: Path):
    import asyncio

    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = HarnessConfig(cwd=ws, shell_environment=ShellEnvironmentPolicy(set_vars={"TEST_VAR": "ok"}))
    shell = ShellTool(cfg)
    # Simulate extended path passed to cwd
    ext_ws = Path("\\\\?\\" + str(strip_extended_prefix(ws).resolve())) if sys.platform == "win32" else ws

    res = asyncio.run(
        shell.execute(
            ToolInvocation(
                params={"command": "python -c \"import os, pandas; print(os.environ['TEST_VAR'], pandas.__name__)\""},
                cwd=ext_ws,
            )
        )
    )
    assert res.success is True
    assert "ok pandas" in res.output


def test_harness_runner_end_to_end_with_mock_transport(isolated_env, tmp_path: Path):
    import asyncio

    ws = tmp_path / "harness_ws"
    ro = tmp_path / "readonly_src"
    ro.mkdir()
    src_csv = ro / "cases.csv"
    src_csv.write_text("Case Number\nC-1\nC-2\nC-3\n", encoding="utf-8")
    before_sha = hashlib.sha256(src_csv.read_bytes()).hexdigest()

    turn = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        turn["n"] += 1
        if turn["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Writing analysis script.",
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "type": "function",
                                        "function": {
                                            "name": "write_file",
                                            "arguments": json.dumps(
                                                {
                                                    "path": "count_cases.py",
                                                    "content": (
                                                        "import os, pandas as pd, json\n"
                                                        "from pathlib import Path\n"
                                                        "df = pd.read_csv(Path(os.environ['SOURCE_INPUT_DIR']) / 'cases.csv')\n"
                                                        "Path('result.json').write_text(json.dumps({'count': len(df)}))\n"
                                                    ),
                                                }
                                            ),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            )
        if turn["n"] == 2:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Executing count_cases.py",
                                "tool_calls": [
                                    {
                                        "id": "c2",
                                        "type": "function",
                                        "function": {
                                            "name": "shell",
                                            "arguments": json.dumps({"command": "python count_cases.py"}),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Completed count_cases.py verification."},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    res = asyncio.run(
        run_harness_task_async(
            run_id="run-test-1",
            stage="rules",
            agent_id="HarnessTest",
            goal="Count cases in cases.csv",
            workspace_dir=ws,
            readonly_dirs=[ro],
            env_vars={"SOURCE_INPUT_DIR": str(ro)},
            provider="lmstudio",
            base_url="http://mock.local/v1",
            transport=httpx.MockTransport(handler),
            max_turns=6,
        )
    )

    assert res.success is True
    assert res.tool_calls_count == 2
    assert "count_cases.py" in res.files_written
    assert "result.json" in res.files_written
    assert json.loads((ws / "result.json").read_text())["count"] == 3
    assert hashlib.sha256(src_csv.read_bytes()).hexdigest() == before_sha

