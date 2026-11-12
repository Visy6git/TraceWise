"""Tests for the integrated TraceWise coding-agent harness (app/harness/)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest

from app.config import BEDROCK_MODEL_ID, LMSTUDIO_MODEL_ID
from app.harness.config import ApprovalPolicy, HarnessConfig, ModelConfig, ShellEnvironmentPolicy
from app.harness.events import StreamEventType
from app.harness.llm_client import LLMClient
from app.harness.paths import strip_extended_prefix
from app.harness.runner import run_harness_task_async
from app.harness.tools.base import ToolInvocation
from app.harness.tools.edit_file import EditTool
from app.harness.tools.read_file import ReadFileTool
from app.harness.tools.shell import ShellTool
from app.harness.tools.write_file import WriteFileTool


def test_bedrock_provider_does_not_use_lmstudio_default_model():
    cfg = HarnessConfig(
        provider="bedrock",
        model=ModelConfig(name=LMSTUDIO_MODEL_ID),
    )
    assert cfg.effective_model_name() == BEDROCK_MODEL_ID


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


def test_bedrock_leaves_tool_choice_automatic_for_model_compatibility(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.harness import llm_client as llm_client_module

    requests = []

    class FakeBedrockClient:
        def converse(self, **kwargs):
            requests.append(kwargs)
            return {"output": {"message": {"content": [{"text": "done"}]}}}

    fake_session = SimpleNamespace(client=lambda *_args, **_kwargs: FakeBedrockClient())
    monkeypatch.setattr(llm_client_module.boto3, "Session", lambda **_kwargs: fake_session)

    async def call(messages):
        cfg = HarnessConfig(provider="bedrock")
        client = LLMClient(cfg)
        async for _ in client.chat_completion(
            messages,
            tools=[{"name": "write_file", "parameters": {"type": "object", "properties": {}}}],
        ):
            pass

    asyncio.run(call([{"role": "user", "content": "write a file"}]))
    asyncio.run(
        call(
            [
                {"role": "user", "content": "write a file"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "write_file", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "written"},
            ]
        )
    )

    assert "toolChoice" not in requests[0]["toolConfig"]
    assert "toolChoice" not in requests[1]["toolConfig"]


def _run_fake_bedrock_converse(monkeypatch, *, cfg_kwargs=None, converse_impl=None):
    """Drive a single Bedrock chat_completion through a fake client and return captured kwargs."""
    import asyncio
    from types import SimpleNamespace

    from app.harness import llm_client as llm_client_module

    requests: list[dict] = []

    class FakeBedrockClient:
        def converse(self, **kwargs):
            requests.append(kwargs)
            if converse_impl is not None:
                return converse_impl(len(requests), kwargs)
            return {"output": {"message": {"content": [{"text": "done"}]}}}

    fake_session = SimpleNamespace(client=lambda *_a, **_k: FakeBedrockClient())
    monkeypatch.setattr(llm_client_module.boto3, "Session", lambda **_k: fake_session)

    async def call():
        cfg = HarnessConfig(provider="bedrock", **(cfg_kwargs or {}))
        client = LLMClient(cfg)
        events = []
        async for ev in client.chat_completion([{"role": "user", "content": "hi"}]):
            events.append(ev)
        return events

    events = asyncio.run(call())
    return requests, events


def test_bedrock_omits_temperature_by_default(monkeypatch):
    """Newer Bedrock models reject `temperature`; it must not be sent unless opted in."""
    requests, _ = _run_fake_bedrock_converse(monkeypatch)
    assert requests, "converse was not called"
    inference = requests[0]["inferenceConfig"]
    assert "temperature" not in inference
    assert inference["maxTokens"] > 0


def test_bedrock_includes_temperature_when_explicitly_enabled(monkeypatch):
    requests, _ = _run_fake_bedrock_converse(
        monkeypatch, cfg_kwargs={"bedrock_send_temperature": True}
    )
    assert "temperature" in requests[0]["inferenceConfig"]


def test_bedrock_self_heals_when_model_reports_temperature_deprecated(monkeypatch):
    """If a model still rejects a sent field, strip it and retry once rather than failing."""
    # Record whether temperature was present at each call time (the kwargs dict is mutated
    # in place on retry, so capture presence here rather than inspecting it afterwards).
    temp_seen: list[bool] = []

    def converse_impl(call_number, kwargs):
        temp_seen.append("temperature" in kwargs["inferenceConfig"])
        if call_number == 1 and "temperature" in kwargs["inferenceConfig"]:
            raise RuntimeError(
                "An error occurred (ValidationException): `temperature` is deprecated for this model."
            )
        return {"output": {"message": {"content": [{"text": "ok"}]}}}

    _, events = _run_fake_bedrock_converse(
        monkeypatch,
        cfg_kwargs={"bedrock_send_temperature": True},
        converse_impl=converse_impl,
    )
    # First call carried temperature and failed; retry dropped it and succeeded.
    assert temp_seen == [True, False]
    assert not [e for e in events if e.type == StreamEventType.ERROR]
    assert [e for e in events if e.type == StreamEventType.TEXT_DELTA]


def test_bedrock_merges_consecutive_tool_results_into_one_user_message(monkeypatch):
    """Bedrock requires all toolResults for an assistant turn in one following user message."""
    import asyncio
    from types import SimpleNamespace

    from app.harness import llm_client as llm_client_module

    requests: list[dict] = []

    class Fake:
        def converse(self, **kwargs):
            requests.append(kwargs)
            return {"output": {"message": {"content": [{"text": "ok"}]}}}

    monkeypatch.setattr(
        llm_client_module.boto3,
        "Session",
        lambda **_k: SimpleNamespace(client=lambda *_a, **_k2: Fake()),
    )

    messages = [
        {"role": "user", "content": "do it"},
        {
            "role": "assistant",
            "content": "calling tools",
            "tool_calls": [
                {"id": "t1", "function": {"name": "write_file", "arguments": "{}"}},
                {"id": "t2", "function": {"name": "shell", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "wrote"},
        {"role": "tool", "tool_call_id": "t2", "content": "ran"},
    ]

    async def call():
        cfg = HarnessConfig(provider="bedrock")
        client = LLMClient(cfg)
        async for _ in client.chat_completion(messages):
            pass

    asyncio.run(call())
    msgs = requests[0]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    last = msgs[-1]["content"]
    ids = [b["toolResult"]["toolUseId"] for b in last if "toolResult" in b]
    assert ids == ["t1", "t2"]


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
