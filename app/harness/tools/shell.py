"""Scoped shell execution tool with .venv Python on PATH and Windows-safe cwd."""
from __future__ import annotations

import asyncio
import fnmatch
import os
import signal
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from app.harness.paths import is_within_dir, strip_extended_prefix
from app.harness.tools.base import Tool, ToolConfirmation, ToolInvocation, ToolKind, ToolResult

BLOCKED_PATTERNS = {
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /*",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    "mkfs",
    "fdisk",
    "parted",
    ":(){ :|:& };:",
    "chmod 777 /",
    "chmod -R 777",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "format ",
}


class ShellParams(BaseModel):
    command: str = Field(..., description="Shell command to execute inside workspace")
    timeout: int = Field(180, ge=1, le=600, description="Timeout in seconds (default 180)")
    cwd: str | None = Field(None, description="Optional subdirectory relative to workspace cwd")


class ShellTool(Tool):
    name = "shell"
    kind = ToolKind.SHELL
    description = (
        "Execute a shell command (e.g. `python script.py` or `python -m pytest`) inside the workspace. "
        "The project virtual environment is pre-configured on PATH and SOURCE_INPUT_DIR is exposed read-only."
    )
    schema = ShellParams

    async def get_confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        params = ShellParams(**invocation.params)
        cmd_lower = params.command.lower()
        dangerous = any(b in cmd_lower for b in BLOCKED_PATTERNS)
        return ToolConfirmation(
            tool_name=self.name,
            params=invocation.params,
            description=f"Execute: {params.command}",
            command=params.command,
            is_dangerous=dangerous,
        )

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = ShellParams(**invocation.params)
        cmd_lower = params.command.lower().strip()

        for blocked in BLOCKED_PATTERNS:
            if blocked in cmd_lower:
                return ToolResult.error_result(
                    f"Command blocked by safety policy: {params.command}",
                    metadata={"blocked": True},
                )

        base_cwd = strip_extended_prefix(invocation.cwd).resolve()
        if params.cwd:
            req_cwd = strip_extended_prefix(Path(params.cwd))
            cwd = req_cwd.resolve() if req_cwd.is_absolute() else (base_cwd / req_cwd).resolve()
            if not is_within_dir(cwd, base_cwd):
                return ToolResult.error_result("Shell cwd cannot escape the workspace root")
        else:
            cwd = base_cwd

        if not cwd.exists():
            return ToolResult.error_result(f"Working directory does not exist: {cwd}")

        env = self._build_environment(cwd)
        if sys.platform == "win32":
            # Use subprocess_shell on Windows so list2cmdline does not corrupt quoted args in `cmd.exe /c`
            process = await asyncio.create_subprocess_shell(
                params.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=env,
            )
        else:
            process = await asyncio.create_subprocess_exec(
                "/bin/bash",
                "-c",
                params.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=env,
                start_new_session=True,
            )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                process.communicate(),
                timeout=params.timeout,
            )
        except asyncio.TimeoutError:
            if sys.platform != "win32":
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except OSError:
                    process.kill()
            else:
                process.kill()
            await process.wait()
            return ToolResult.error_result(f"Command timed out after {params.timeout}s")

        stdout = stdout_data.decode("utf-8", errors="replace")
        stderr = stderr_data.decode("utf-8", errors="replace")
        exit_code = process.returncode

        parts: list[str] = []
        if stdout.strip():
            parts.append(stdout.rstrip())
        if stderr.strip():
            parts.append("--- stderr ---\n" + stderr.rstrip())
        if exit_code != 0:
            parts.append(f"Exit code: {exit_code}")

        output = "\n".join(parts) if parts else "(command completed with no output)"
        max_chars = 60 * 1024
        truncated = False
        if len(output) > max_chars:
            output = output[:max_chars] + "\n... [output truncated]"
            truncated = True

        return ToolResult(
            success=(exit_code == 0),
            output=output,
            error=stderr.strip() or f"Command exited with code {exit_code}" if exit_code != 0 else None,
            truncated=truncated,
            exit_code=exit_code,
        )

    def _build_environment(self, cwd: Path) -> dict[str, str]:
        env = os.environ.copy()
        policy = self.config.shell_environment

        if not policy.ignore_default_excludes:
            for pattern in policy.exclude_patterns:
                for key in list(env.keys()):
                    if fnmatch.fnmatch(key.upper(), pattern.upper()):
                        del env[key]

        # Ensure the active interpreter directory (e.g. .venv\Scripts) is first on PATH
        venv_bin = str(Path(sys.executable).resolve().parent)
        existing_path = env.get("PATH", "")
        if venv_bin and venv_bin not in existing_path.split(os.pathsep):
            env["PATH"] = f"{venv_bin}{os.pathsep}{existing_path}" if existing_path else venv_bin
        env["PYTHON_EXECUTABLE"] = str(Path(sys.executable).resolve())
        env["PYTHONIOENCODING"] = "utf-8"
        env["CLAIM_WORKSPACE_DIR"] = str(cwd)

        if policy.set_vars:
            for k, v in policy.set_vars.items():
                env[k] = str(v)

        return env

