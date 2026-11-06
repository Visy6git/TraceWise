"""Virtual Execution Sandbox for Autonomous Data Analysis Agents.
Allows agents to write, execute, inspect, and delete Python programs in an isolated
per-run workspace while protecting source documents as strictly READ-ONLY.
Supports Docker container isolation when available, with hardened process fallback.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import os
import shutil
import stat
import subprocess
import sys
import time
from typing import Any


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    output_files: list[str] = field(default_factory=list)
    timed_out: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "output_files": self.output_files,
            "timed_out": self.timed_out,
            "error": self.error,
        }


class AgentSandbox:
    """Isolated execution harness for an agent run with read-only source enforcement."""

    def __init__(self, run_dir: Path, input_dir: Path):
        self.run_dir = run_dir.resolve()
        self.input_dir = input_dir.resolve()
        self.sandbox_dir = (self.run_dir / "sandbox").resolve()
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        venv_py = sys.prefix + "/Scripts/python.exe" if os.name == "nt" else sys.prefix + "/bin/python"
        self.python_bin = venv_py if os.path.exists(venv_py) else sys.executable
        self._enforce_input_readonly()

    def _enforce_input_readonly(self):
        """Ensures all source files in the input directory have read-only filesystem attributes."""
        if not self.input_dir.exists():
            return
        for p in self.input_dir.rglob("*"):
            if p.is_file():
                try:
                    os.chmod(p, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
                except Exception:
                    pass

    def _resolve_sandbox_path(self, relative_path: str) -> Path:
        clean = Path(relative_path).name
        target = (self.sandbox_dir / clean).resolve()
        if not str(target).startswith(str(self.sandbox_dir)):
            raise PermissionError(f"Path traversal detected: {relative_path}")
        return target

    def write_file(self, filename: str, content: str) -> dict[str, Any]:
        """Creates or updates a file in the sandbox virtual workspace."""
        path = self._resolve_sandbox_path(filename)
        path.write_text(content, encoding="utf-8")
        return {
            "filename": path.name,
            "size": path.stat().st_size,
            "status": "written",
            "path": str(path),
        }

    def read_file(self, filename: str) -> str:
        """Reads a file from either the sandbox or the read-only input dir."""
        s_path = self._resolve_sandbox_path(filename)
        if s_path.is_file():
            return s_path.read_text(encoding="utf-8", errors="replace")
        i_path = (self.input_dir / Path(filename).name).resolve()
        if i_path.is_file():
            return i_path.read_text(encoding="utf-8", errors="replace")
        raise FileNotFoundError(f"File not found in sandbox or input: {filename}")

    def delete_file(self, filename: str) -> dict[str, Any]:
        """Deletes a file from the sandbox workspace. Strictly forbids deleting inputs."""
        clean = Path(filename).name
        input_candidate = self.input_dir / clean
        if input_candidate.is_file():
            raise PermissionError(f"Cannot delete source document: {filename} is protected as read-only.")

        path = self._resolve_sandbox_path(filename)
        if not path.exists():
            raise FileNotFoundError(f"File does not exist in sandbox: {filename}")
        path.unlink()
        return {"filename": clean, "status": "deleted"}

    def list_files(self) -> list[dict[str, Any]]:
        """Lists files in the sandbox workspace."""
        files = []
        for p in self.sandbox_dir.iterdir():
            if p.is_file():
                files.append({
                    "name": p.name,
                    "size": p.stat().st_size,
                    "modified": p.stat().st_mtime,
                    "is_script": p.suffix == ".py",
                })
        return sorted(files, key=lambda x: x["name"])

    def execute_python(self, script_name: str, timeout_seconds: int = 25) -> ExecutionResult:
        """Executes a Python script inside the sandbox workspace."""
        script_path = self._resolve_sandbox_path(script_name)
        if not script_path.is_file():
            return ExecutionResult(
                stdout="",
                stderr=f"Script file '{script_name}' does not exist in sandbox.",
                exit_code=1,
                duration_ms=0,
                error="ScriptNotFound",
            )

        # Re-enforce read-only state on source files prior to execution
        self._enforce_input_readonly()

        before_files = set(p.name for p in self.sandbox_dir.iterdir() if p.is_file())

        # Sanitized isolated environment (strip AWS secrets, host credentials)
        safe_keys = {
            "PATH", "SYSTEMROOT", "WINDIR", "PYTHONPATH", "TEMP", "TMP",
            "HOMEDRIVE", "HOMEPATH", "USERPROFILE", "LANG", "LC_ALL",
        }
        env = {k: v for k, v in os.environ.items() if k.upper() in safe_keys}
        env["PYTHONUNBUFFERED"] = "1"
        env["SOURCE_INPUT_DIR"] = str(self.input_dir)
        env["SANDBOX_DIR"] = str(self.sandbox_dir)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        # Check if Docker execution is explicitly configured and available
        docker_enabled = os.getenv("DOCKER_SANDBOX_ENABLED", "false").lower() == "true"
        docker_bin = shutil.which("docker")
        if docker_enabled and docker_bin:
            return self._execute_docker(script_name, timeout_seconds, before_files)

        start_t = time.perf_counter()
        try:
            proc = subprocess.run(
                [self.python_bin, str(script_path)],
                cwd=str(self.sandbox_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            duration_ms = round((time.perf_counter() - start_t) * 1000, 2)
            after_files = set(p.name for p in self.sandbox_dir.iterdir() if p.is_file())
            new_files = sorted(list(after_files - before_files))

            return ExecutionResult(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_code=proc.returncode,
                duration_ms=duration_ms,
                output_files=new_files,
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            duration_ms = round((time.perf_counter() - start_t) * 1000, 2)
            return ExecutionResult(
                stdout="",
                stderr=f"Execution timed out after {timeout_seconds} seconds.",
                exit_code=-1,
                duration_ms=duration_ms,
                timed_out=True,
                error="TimeoutExpired",
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_t) * 1000, 2)
            return ExecutionResult(
                stdout="",
                stderr=str(exc),
                exit_code=1,
                duration_ms=duration_ms,
                error=str(exc),
            )

    def _execute_docker(self, script_name: str, timeout_seconds: int, before_files: set[str]) -> ExecutionResult:
        """Docker-based container execution with read-only source mount and isolated network."""
        start_t = time.perf_counter()
        image = os.getenv("SANDBOX_DOCKER_IMAGE", "python:3.11-slim")
        cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--memory", "512m",
            "--cpus", "1.0",
            "-v", f"{self.input_dir}:/input:ro",
            "-v", f"{self.sandbox_dir}:/workspace:rw",
            "-w", "/workspace",
            "-e", "SOURCE_INPUT_DIR=/input",
            "-e", "SANDBOX_DIR=/workspace",
            image,
            "python", script_name,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            duration_ms = round((time.perf_counter() - start_t) * 1000, 2)
            after_files = set(p.name for p in self.sandbox_dir.iterdir() if p.is_file())
            new_files = sorted(list(after_files - before_files))
            return ExecutionResult(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_code=proc.returncode,
                duration_ms=duration_ms,
                output_files=new_files,
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            duration_ms = round((time.perf_counter() - start_t) * 1000, 2)
            return ExecutionResult(
                stdout="",
                stderr=f"Docker sandbox execution timed out after {timeout_seconds} seconds.",
                exit_code=-1,
                duration_ms=duration_ms,
                timed_out=True,
                error="TimeoutExpired",
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_t) * 1000, 2)
            return ExecutionResult(
                stdout="",
                stderr=str(exc),
                exit_code=1,
                duration_ms=duration_ms,
                error=str(exc),
            )
