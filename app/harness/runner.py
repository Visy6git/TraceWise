"""High-level headless runner for executing the TraceWise harness inside Stage 1 & Stage 2."""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.harness.agent import HarnessAgent
from app.harness.config import ApprovalPolicy, HarnessConfig, ModelConfig, ShellEnvironmentPolicy
from app.harness.events import AgentEventType
from app.harness.llm_client import LLMClient
from app.harness.paths import strip_extended_prefix, to_extended_path
from app.services.event_stream import default_broker


@dataclass
class HarnessRunResult:
    success: bool
    final_response: str
    turns: int
    tool_calls_count: int
    tool_history: list[dict[str, Any]] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    error: str | None = None
    elapsed_seconds: float = 0.0


def _snapshot_hashes(dirs: list[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for d in dirs:
        clean_d = strip_extended_prefix(d).resolve()
        if not clean_d.exists():
            continue
        for p in sorted(clean_d.rglob("*")):
            ext_p = to_extended_path(p)
            if ext_p.is_file():
                hashes[str(p)] = hashlib.sha256(ext_p.read_bytes()).hexdigest()
    return hashes


def _sanitize_tool_payload(tool_name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    blocked_keys = {
        "rows", "records", "sample_rows", "sample_values", "unique_values",
        "raw_rows", "matched_rows", "claim_data", "patient_data", "person_data",
        "case_data", "patients", "subjects", "cases", "patient_list", "raw_data",
        "data_rows", "password", "secret", "token",
    }
    sanitized: dict[str, Any] = {}
    for k, v in args.items():
        if k.lower() in blocked_keys:
            sanitized[k] = "<redacted>"
            continue
        if tool_name in {"write_file", "edit_file"} and k in {"content", "replacement", "target"}:
            str_val = str(v)
            if len(str_val) > 200:
                sanitized[k] = str_val[:180] + f"... <truncated {len(str_val)} chars>"
            else:
                sanitized[k] = str_val
        elif isinstance(v, (str, bytes)):
            str_val = str(v)
            sanitized[k] = str_val[:240] + ("..." if len(str_val) > 240 else "")
        elif isinstance(v, list) and len(v) > 20:
            sanitized[k] = [str(x)[:80] for x in v[:10]] + [f"... <{len(v) - 10} more items>"]
        elif isinstance(v, dict):
            sanitized[k] = {str(dk): str(dv)[:80] for dk, dv in list(v.items())[:10]}
        else:
            sanitized[k] = v
    return sanitized


def _sanitize_tool_output(output: str) -> str:
    if not output:
        return ""
    return str(output)[:400]


async def run_harness_task_async(
    *,
    run_id: str,
    stage: str,
    agent_id: str,
    goal: str,
    workspace_dir: Path,
    readonly_dirs: list[Path] | None = None,
    env_vars: dict[str, str] | None = None,
    developer_instructions: str | None = None,
    max_turns: int = 24,
    provider: str | None = None,
    model_id: str | None = None,
    base_url: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    emit_events: bool = True,
) -> HarnessRunResult:
    """Execute the coding-agent harness against `workspace_dir` and stream AG-UI telemetry."""
    start = time.monotonic()
    clean_ws = strip_extended_prefix(workspace_dir).resolve()
    clean_ws.mkdir(parents=True, exist_ok=True)
    ro_dirs = [strip_extended_prefix(p).resolve() for p in (readonly_dirs or [])]

    before_hashes = _snapshot_hashes(ro_dirs)

    model_cfg = ModelConfig()
    if model_id:
        model_cfg.name = model_id

    cfg_kwargs: dict[str, Any] = {
        "model": model_cfg,
        "cwd": clean_ws,
        "readonly_dirs": ro_dirs,
        "shell_environment": ShellEnvironmentPolicy(set_vars=env_vars or {}),
        "max_turns": max_turns,
        "approval": ApprovalPolicy.AUTO,
        "developer_instructions": developer_instructions,
    }
    if provider:
        cfg_kwargs["provider"] = provider
    if base_url:
        cfg_kwargs["base_url"] = base_url

    config = HarnessConfig(**cfg_kwargs)
    client = LLMClient(config, transport=transport) if transport is not None else None

    tool_history: list[dict[str, Any]] = []
    files_written: list[str] = []
    final_response = ""
    error_msg: str | None = None
    turns = 0

    try:
        async with HarnessAgent(config, llm_client=client) as agent:
            async for event in agent.run(goal):
                if event.type == AgentEventType.TEXT_COMPLETE:
                    turns += 1
                    final_response = str(event.data.get("content") or "")
                elif event.type == AgentEventType.TOOL_CALL_START:
                    if turns == 0:
                        turns = 1
                    tool_name = str(event.data.get("name", ""))
                    raw_args = event.data.get("arguments") or {}
                    call_id = str(event.data.get("call_id", ""))
                    safe_args = _sanitize_tool_payload(tool_name, raw_args)
                    tool_history.append(
                        {"event": "start", "call_id": call_id, "tool": tool_name, "args": safe_args}
                    )
                    if emit_events:
                        default_broker.emit_tool_call(
                            run_id,
                            tool_call_id=call_id,
                            tool_name=tool_name,
                            args=safe_args,
                        )
                        default_broker.emit_activity(
                            run_id=run_id,
                            stage=stage,
                            title=f"{agent_id}: {tool_name}",
                            detail=str(safe_args)[:140],
                            kind="tool",
                            agent=agent_id,
                        )
                elif event.type == AgentEventType.TOOL_CALL_COMPLETE:
                    call_id = str(event.data.get("call_id", ""))
                    tool_name = str(event.data.get("name", ""))
                    ok = bool(event.data.get("success"))
                    meta = event.data.get("metadata") or {}
                    if ok and tool_name in {"write_file", "edit_file"} and meta.get("path"):
                        files_written.append(str(meta["path"]))
                    output_preview = _sanitize_tool_output(str(event.data.get("output") or ""))
                    tool_history.append(
                        {
                            "event": "complete",
                            "call_id": call_id,
                            "tool": tool_name,
                            "success": ok,
                            "exit_code": event.data.get("exit_code"),
                            "error": event.data.get("error"),
                            "output_preview": output_preview,
                        }
                    )
                    if emit_events:
                        default_broker.emit_tool_result(
                            run_id,
                            tool_call_id=call_id,
                            result_summary=output_preview[:240],
                        )
                elif event.type == AgentEventType.AGENT_ERROR:
                    error_msg = str(event.data.get("error") or "Unknown harness error")
                    turns = max(turns, 1)
                elif event.type == AgentEventType.AGENT_END:
                    if not final_response and event.data.get("response"):
                        final_response = str(event.data["response"])
    except Exception as exc:
        error_msg = str(exc)

    # Verify immutability of read-only inputs
    after_hashes = _snapshot_hashes(ro_dirs)
    if before_hashes != after_hashes:
        error_msg = "SECURITY VIOLATION: read-only source file checksums changed during harness run"

    # Discover all workspace files created or updated
    discovered_files = [
        str(p.relative_to(clean_ws)).replace("\\", "/")
        for p in sorted(clean_ws.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    ]

    return HarnessRunResult(
        success=(error_msg is None),
        final_response=final_response,
        turns=turns,
        tool_calls_count=sum(1 for h in tool_history if h.get("event") == "start"),
        tool_history=tool_history,
        files_written=discovered_files,
        error=error_msg,
        elapsed_seconds=round(time.monotonic() - start, 3),
    )


def run_harness_task(**kwargs: Any) -> HarnessRunResult:
    """Synchronous entry point for calling the async harness from worker threads."""
    return asyncio.run(run_harness_task_async(**kwargs))

