from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable
from openpyxl import load_workbook
import pandas as pd

from app.services.excel_profile import profile_xlsx, profile_to_markdown
from app.services.llm_client import invoke_agent_turn, llm_status_info

AguiEmitter = Callable[[str, dict[str, Any]], None]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit_agui(emitter: AguiEmitter | None, event_type: str, **payload: Any) -> None:
    if emitter:
        emitter(event_type, {"timestamp": _utcnow(), **payload})


def safe_workbook_stem(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("_")[:80]
    return stem or "workbook"


# ==================== 100-LINE CONTEXT EXTRACTOR ====================
def extract_excel_100_line_preview(path: Path, max_lines: int = 100) -> str:
    """Read up to the first 100 non-empty lines across sheets of an Excel workbook as compact agent context."""
    suffix = path.suffix.lower()
    lines: list[str] = [f"FILE: {path.name} ({suffix.lstrip('.').upper()})"]
    remaining = max_lines

    def _fmt_row(row_no: int, raw_cells: list[Any], emitted_in_sheet: int) -> str | None:
        # Keep banner/header/first 12 rows full detail; compact later sample rows so 100 lines stay fast for local LLMs
        cell_cap = 50 if emitted_in_sheet < 12 else 22
        vals = [str(v).replace("\n", " ").strip()[:cell_cap] if (v is not None and pd.notna(v)) else "" for v in raw_cells]
        if not any(vals):
            return None
        while vals and not vals[-1]:
            vals.pop()
        line = f"Row {row_no}: " + " | ".join(vals)
        return line[:320] if emitted_in_sheet >= 12 else line[:600]

    if suffix == ".xls":
        book = pd.ExcelFile(path, engine="xlrd")
        lines.append(f"SHEETS ({len(book.sheet_names)}): {', '.join(book.sheet_names)}")
        for sheet_name in book.sheet_names:
            if remaining <= 0:
                break
            raw = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=object, engine="xlrd", nrows=remaining + 10)
            lines.append(f"\n--- SHEET: {sheet_name} ---")
            emitted = 0
            for idx, row in raw.iterrows():
                if remaining <= 0:
                    break
                formatted = _fmt_row(int(idx) + 1, row.tolist(), emitted)
                if formatted:
                    lines.append(formatted)
                    emitted += 1
                    remaining -= 1
        return "\n".join(lines)

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        lines.append(f"SHEETS ({len(wb.sheetnames)}): {', '.join(wb.sheetnames)}")
        for ws in wb.worksheets:
            if remaining <= 0:
                break
            lines.append(f"\n--- SHEET: {ws.title} (max_row={ws.max_row}, max_col={ws.max_column}) ---")
            emitted = 0
            for row_no, row in enumerate(ws.iter_rows(min_row=1, max_row=min(ws.max_row or 200, 300), values_only=True), 1):
                if remaining <= 0:
                    break
                formatted = _fmt_row(row_no, list(row), emitted)
                if formatted:
                    lines.append(formatted)
                    emitted += 1
                    remaining -= 1
    finally:
        wb.close()

    return "\n".join(lines)


# ==================== ISOLATED SANDBOX TOOLS ====================
class IsolatedExcelSandbox:
    """Isolated per-file workspace with path-confined file tools and terminal execution."""

    def __init__(self, agent_dir: Path, source_excel: Path):
        self.agent_dir = agent_dir.resolve()
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.source_filename = source_excel.name
        self.local_excel = self.agent_dir / source_excel.name
        if not self.local_excel.exists():
            shutil.copy2(source_excel, self.local_excel)

    def _safe_path(self, filename: str) -> Path:
        rel = Path((filename or "").strip())
        if rel.is_absolute():
            raise ValueError("Use a relative filename inside the isolated workspace.")
        target = (self.agent_dir / rel).resolve()
        if target != self.agent_dir and self.agent_dir not in target.parents:
            raise ValueError("Path escapes the isolated workspace.")
        return target

    def write_file(self, filename: str, content: str) -> dict[str, Any]:
        target = self._safe_path(filename)
        if target.name == self.source_filename:
            return {"ok": False, "error": "The assigned Excel workbook is read-only and cannot be overwritten."}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", encoding="utf-8")
        return {"ok": True, "filename": str(target.relative_to(self.agent_dir)), "bytes": target.stat().st_size}

    def edit_file(self, filename: str, target: str, replacement: str) -> dict[str, Any]:
        path = self._safe_path(filename)
        if path.name == self.source_filename:
            return {"ok": False, "error": "The assigned Excel workbook is read-only."}
        if not path.is_file():
            return {"ok": False, "error": f"File '{filename}' does not exist."}
        text = path.read_text(encoding="utf-8")
        if target not in text:
            return {"ok": False, "error": "Target text not found in file."}
        updated = text.replace(target, replacement, 1)
        path.write_text(updated, encoding="utf-8")
        return {"ok": True, "filename": str(path.relative_to(self.agent_dir)), "bytes": path.stat().st_size}

    def read_file(self, filename: str, start_line: int = 1, end_line: int = 200) -> dict[str, Any]:
        path = self._safe_path(filename)
        if not path.is_file():
            return {"ok": False, "error": f"File '{filename}' does not exist."}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        s = max(1, int(start_line or 1))
        e = min(len(lines), int(end_line or 200))
        snippet = "\n".join(f"{i}: {lines[i - 1]}" for i in range(s, e + 1))
        return {"ok": True, "total_lines": len(lines), "content": snippet[:10000]}

    def run_terminal(self, command: str) -> dict[str, Any]:
        cmd = (command or "").strip()
        if not cmd:
            return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "Empty command."}
        low = cmd.lower()
        # Basic guardrails keeping terminal execution strictly inside the isolated workbook folder
        forbidden = ["..", "rm -rf /", "del /s", "format ", "shutdown", "powershell -enc", "invoke-webrequest", "curl ", "wget "]
        if any(tok in low for tok in forbidden):
            return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "Command rejected by isolated sandbox policy."}

        # Ensure `python` / `python3` always invokes the active venv Python with pandas/openpyxl/xlrd
        py_exe = f'"{sys.executable}"'
        if re.match(r"^python3?(?:\.exe)?\b", cmd, flags=re.I):
            cmd = re.sub(r"^python3?(?:\.exe)?\b", lambda _m: py_exe, cmd, count=1, flags=re.I)

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["EXCEL_FILE"] = self.source_filename
        venv_bin = str(Path(sys.executable).parent)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"

        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.agent_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            return {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": (proc.stdout or "")[:12000],
                "stderr": (proc.stderr or "")[:4000],
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "Command timed out after 45s."}
        except Exception as exc:
            return {"ok": False, "exit_code": -1, "stdout": "", "stderr": str(exc)}


EXPLORER_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file (e.g. analysis.py or <name>.md) inside your isolated workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Relative filename inside the isolated workspace"},
                    "content": {"type": "string", "description": "Full UTF-8 text content to write"},
                },
                "required": ["filename", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace an exact target substring in an existing file inside your isolated workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Relative filename to edit"},
                    "target": {"type": "string", "description": "Exact existing text to replace"},
                    "replacement": {"type": "string", "description": "Replacement text"},
                },
                "required": ["filename", "target", "replacement"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read lines from a file inside your isolated workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Relative filename to read"},
                    "start_line": {"type": "integer", "description": "1-based start line"},
                    "end_line": {"type": "integer", "description": "1-based end line"},
                },
                "required": ["filename"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_terminal",
            "description": "Run a terminal command (such as `python analysis.py`) inside your isolated workspace where the Excel file sits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run (e.g. `python analysis.py`)"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_exploration",
            "description": "Call this ONLY after running analysis.py cleanly and writing the detailed Markdown report file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "md_file": {"type": "string", "description": "Filename of the generated Markdown report"},
                    "analysis_py_file": {"type": "string", "description": "Filename of the generated Python analysis script (analysis.py)"},
                    "summary_notes": {"type": "string", "description": "Brief 1-2 sentence summary of key findings"},
                },
                "required": ["md_file", "analysis_py_file", "summary_notes"],
                "additionalProperties": False,
            },
        },
    },
]


EXCEL_EXPLORER_SYSTEM_PROMPT = """You are an Expert Pharmacovigilance Data Exploration Agent operating inside an isolated sandbox directory containing ONE assigned Excel workbook.

You have terminal and file tools (`write_file`, `edit_file`, `read_file`, `run_terminal`, `complete_exploration`).
The assigned Excel file is located right in your current working directory (exact filename provided in the prompt, and also in env var `EXCEL_FILE`).

YOUR MISSION — Perform an in-depth, verified analysis of this Excel workbook and produce TWO artifacts:
1. **`analysis.py`** — A clean, well-commented, runnable Python script (using `pandas` / `openpyxl` / `xlrd`) that:
   - Contains thorough top-level and inline comments documenting the exact sheet names, exact header row number (1-based and 0-based), banner/metadata rows to skip, column names, date formats, and any structural quirks so the NEXT downstream agent can immediately read `analysis.py` to navigate this Excel file without guessing.
   - Provides clean helper functions (e.g. `load_sheet(...)` and `analyze_workbook()`) and prints a complete factual diagnostic summary when executed.
2. **`{md_filename}`** — An in-depth, detailed Markdown data dictionary & analytical report written strictly from the verified output of `python analysis.py` (NEVER invent or estimate numbers!).

MANDATORY ANALYSIS REQUIREMENTS:
1. **Workbook & Sheet Structure**: Sheet names, exact header row index, metadata/title rows above headers, total data rows, total columns.
2. **Column Inventory**: Know every column's Excel letter, exact column name / field name, inferred data type, non-empty count, null count, and **distinct values count**.
3. **Smart Cardinality Rule (CRITICAL)**:
   - **DO NOT list individual values** for unique identifier / high-cardinality columns where nearly every row is unique (such as `Patient ID`, `Case Number`, `ICSR ID`, `Record ID`, free-text narratives). For these, report ONLY the **distinct value count** (e.g. distinct Case IDs vs total rows, average records per case, whether 1 case has multiple event rows).
   - **DO list distinct values with exact counts** for **defined-set / categorical / terminology columns** where values come from a defined recurring set rather than every value being unique — especially fields like **`Event PT (Primary Path)`**, `Preferred Term`, `SOC`, `HLT`, `Primary Source`, `Initial/Follow-up Flag`, `Seriousness`, `Outcome` / `Fatal`, `Indication`, `Country`, `Drug Role`, `Report Type`, `Status`, etc.!
     - If a defined-set column has ≤ 60 distinct values, list all distinct values with their counts.
     - If it has > 60 distinct values (but is still a recurring terminology field, not unique per row), list the top 40 most frequent values with counts plus the total distinct count.
4. **Reporting Periods & Date Analysis**:
   - Inspect ALL date columns (including compact `YYYYMMDD` numeric/string columns like `Derived-Initial-Approval-Date-(YYYYMMDD)`).
   - Compute exact **earliest date, latest date, reporting period span, and yearly/monthly record counts**.
5. **Basic Pharmacovigilance Quantitative Analysis**:
   - Total data rows vs **distinct Case IDs** (and distinct Patient IDs if present).
   - Breakdown by Initial vs Follow-up (if present), Primary Source / Spontaneous vs Solicited / Study (if present), Seriousness & Fatal outcomes (if present).
   - Highlight any data quality observations (blank rows, duplicate rows, mixed date formats, multi-row cases, header offsets) that the next agent must know.

EXECUTION WORKFLOW:
- Step 1: Review the 100-line workbook preview provided below.
- Step 2: Use `write_file` to create `analysis.py` with thorough comments and full analysis logic.
- Step 3: Use `run_terminal` to execute `python analysis.py`. Inspect the stdout/stderr carefully!
- Step 4: If `analysis.py` errors or reveals additional sheets/date formats/columns to inspect deeper, use `edit_file` and re-run `python analysis.py` via `run_terminal` until it runs cleanly with exit code 0.
- Step 5: Use `write_file` to write `{md_filename}` with rich, well-formatted Markdown tables and sections based strictly on the verified terminal output.
- Step 6: Call `complete_exploration(md_file="{md_filename}", analysis_py_file="analysis.py", summary_notes="...")`.
"""


def _build_verified_fallback_md(
    excel_path: Path,
    profile: dict[str, Any],
    terminal_outputs: list[str],
    analysis_py_name: str,
) -> str:
    """Fallback Markdown assembled strictly from local profile + verified terminal stdout if agent hit max turns."""
    base_md = profile_to_markdown(profile)
    extra = ["", f"## Generated Navigation Script: `{analysis_py_name}`", ""]
    if terminal_outputs:
        extra.append("### Verified `analysis.py` Execution Output")
        extra.append("```text")
        extra.append(terminal_outputs[-1][:8000])
        extra.append("```")
    return base_md + "\n" + "\n".join(extra) + "\n"


def _build_fallback_analysis_py(excel_path: Path, profile: dict[str, Any]) -> str:
    """Clean, well-commented deterministic navigation script fallback if an agent fails to write analysis.py."""
    sheets_meta = [
        {"sheet": s["sheet"], "header_row": s.get("header_row") or 1, "row_count": s.get("row_count", 0)}
        for s in (profile.get("sheets") or [])
    ]
    return f'''"""Auto-generated Excel navigation & analysis helper for {excel_path.name}.

Detected sheets metadata:
{json.dumps(sheets_meta, indent=2)}
"""
from pathlib import Path
import pandas as pd

EXCEL_FILE = Path({excel_path.name!r})
SHEETS = {json.dumps(sheets_meta, indent=2)}


def load_sheet(sheet_name: str, header_row: int = 1) -> pd.DataFrame:
    """Load a sheet using its 1-based Excel header row index."""
    engine = "xlrd" if EXCEL_FILE.suffix.lower() == ".xls" else "openpyxl"
    return pd.read_excel(EXCEL_FILE, sheet_name=sheet_name, header=max(0, header_row - 1), engine=engine)


def summarize() -> None:
    for meta in SHEETS:
        df = load_sheet(meta["sheet"], meta["header_row"])
        print(f"=== Sheet: {{meta['sheet']}} | rows={{len(df)}} | cols={{len(df.columns)}} ===")
        for col in df.columns:
            s = df[col].dropna()
            uniq = s.nunique()
            print(f"  - {{col}}: non_empty={{len(s)}}, distinct={{uniq}}")


if __name__ == "__main__":
    summarize()
'''


def explore_single_workbook_agent(
    excel_path: Path,
    work_dir: Path,
    emitter: AguiEmitter | None = None,
    max_turns: int = 8,
    pause_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Run one isolated terminal-enabled LLM Explorer Agent for a single Excel workbook."""
    if pause_check:
        pause_check()

    filename = excel_path.name
    stem = safe_workbook_stem(excel_path)
    md_filename = f"{stem}.md"
    py_export_name = f"{stem}_analysis.py"

    def emit_file_status(status: str, message: str, **extra: Any):
        _emit_agui(
            emitter,
            "CUSTOM",
            name="source.file_status",
            value={"filename": filename, "status": status, "message": message, **extra},
        )
        _emit_agui(
            emitter,
            "CUSTOM",
            name="agent.activity",
            value={"agent": f"explorer:{stem[:24]}", "message": f"{filename} — {message}", "details": {"file": filename, "status": status, **extra}},
        )

    # 1. Deterministic structural profile (needed by Stage 2 Mapper & column dropdowns) + 100-line context
    emit_file_status("reading_context", "Reading first 100 lines & sheet structure…", step=1)
    profile = profile_xlsx(excel_path)
    preview_100 = extract_excel_100_line_preview(excel_path, max_lines=100)

    # If no LLM is enabled (e.g. offline unit tests), fall back cleanly to deterministic Markdown profile
    if not llm_status_info().get("llm_enabled"):
        md_text = profile_to_markdown(profile)
        (work_dir / md_filename).write_text(md_text, encoding="utf-8")
        py_text = _build_fallback_analysis_py(excel_path, profile)
        (work_dir / py_export_name).write_text(py_text, encoding="utf-8")
        emit_file_status(
            "completed",
            "Profiled workbook (local mode)",
            md_artifact=md_filename,
            py_artifact=py_export_name,
            profile=profile,
        )
        return {"profile": profile, "md_artifact": md_filename, "py_artifact": py_export_name}

    # 2. Prepare isolated per-file sandbox workspace
    agent_dir = work_dir / "explorers" / stem
    sandbox = IsolatedExcelSandbox(agent_dir=agent_dir, source_excel=excel_path)

    system_prompt = EXCEL_EXPLORER_SYSTEM_PROMPT.format(md_filename=md_filename)
    user_prompt = (
        f"You are assigned the Excel workbook `{filename}` inside your isolated workspace.\n"
        f"Target deliverables in your workspace:\n"
        f"1. `analysis.py` (well-commented reusable script to navigate & analyze `{filename}`)\n"
        f"2. `{md_filename}` (in-depth Markdown analysis report based strictly on running `python analysis.py`)\n\n"
        f"Here is the first 100 lines of `{filename}` for initial context:\n\n"
        f"```text\n{preview_100}\n```\n\n"
        f"Begin by writing `analysis.py` using `write_file`, then execute `python analysis.py` with `run_terminal`."
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    completed_flag = False
    terminal_outputs: list[str] = []
    chosen_md = md_filename
    chosen_py = "analysis.py"

    emit_file_status("analyzing", "Agent started in isolated sandbox…", turn=0)

    for turn in range(1, max_turns + 1):
        if pause_check:
            pause_check()

        resp = invoke_agent_turn(
            messages=messages,
            tools=EXPLORER_TOOL_SPECS,
            tool_choice="required",
            max_tokens=2800,
        )
        tool_calls = resp.get("tool_calls") or []
        assistant_text = resp.get("text") or ""

        if not tool_calls:
            # If the agent wrote prose instead of calling a tool, nudge it toward the next unfinished artifact
            has_py = (sandbox.agent_dir / "analysis.py").is_file()
            has_md = (sandbox.agent_dir / md_filename).is_file()
            if has_py and has_md:
                completed_flag = True
                break
            messages.append({"role": "assistant", "content": assistant_text or "(no tool called)"})
            nudge = (
                f"Continue using your tools. Status: analysis.py={'present' if has_py else 'MISSING'}, "
                f"{md_filename}={'present' if has_md else 'MISSING'}. "
                f"Write/run `analysis.py`, write `{md_filename}`, and call `complete_exploration`."
            )
            messages.append({"role": "user", "content": nudge})
            continue

        # Record assistant's tool-call turn concisely in conversation history
        call_summary = "; ".join(f"{c['name']}({', '.join(c['arguments'].keys())})" for c in tool_calls)
        messages.append({"role": "assistant", "content": assistant_text or f"Calling tools: {call_summary}"})

        tool_feedback_parts: list[str] = []
        for call_idx, call in enumerate(tool_calls):
            tname = call["name"]
            targs = call.get("arguments") or {}
            tc_id = f"tc-exp-{stem[:12]}-{turn}-{call_idx}"

            _emit_agui(emitter, "TOOL_CALL_START", toolCallId=tc_id, toolCallName=tname)
            _emit_agui(
                emitter,
                "TOOL_CALL_ARGS",
                toolCallId=tc_id,
                delta=json.dumps({"file": filename, "tool": tname, "target": targs.get("filename") or targs.get("command") or ""}),
            )

            if tname == "write_file":
                target_name = str(targs.get("filename") or "")
                if target_name.endswith(".md"):
                    emit_file_status("writing_report", f"Writing {target_name}…", turn=turn, tool=tname)
                else:
                    emit_file_status("writing_code", f"Writing {target_name or 'script'}…", turn=turn, tool=tname)
                result = sandbox.write_file(target_name, str(targs.get("content") or ""))
            elif tname == "edit_file":
                target_name = str(targs.get("filename") or "")
                emit_file_status("editing_code", f"Editing {target_name}…", turn=turn, tool=tname)
                result = sandbox.edit_file(target_name, str(targs.get("target") or ""), str(targs.get("replacement") or ""))
            elif tname == "read_file":
                result = sandbox.read_file(
                    str(targs.get("filename") or ""),
                    start_line=targs.get("start_line") or 1,
                    end_line=targs.get("end_line") or 200,
                )
            elif tname == "run_terminal":
                cmd = str(targs.get("command") or "")
                emit_file_status("running_terminal", f"Running `{cmd[:48]}`…", turn=turn, tool=tname)
                result = sandbox.run_terminal(cmd)
                if result.get("stdout"):
                    terminal_outputs.append(result["stdout"])
            elif tname == "complete_exploration":
                chosen_md = str(targs.get("md_file") or md_filename)
                chosen_py = str(targs.get("analysis_py_file") or "analysis.py")
                has_md = (sandbox.agent_dir / chosen_md).is_file()
                has_py = (sandbox.agent_dir / chosen_py).is_file()
                if has_md and has_py:
                    completed_flag = True
                    result = {"ok": True, "status": "exploration_completed"}
                else:
                    result = {
                        "ok": False,
                        "error": f"Cannot complete yet: {chosen_py} exists={has_py}, {chosen_md} exists={has_md}. Create both files first.",
                    }
            else:
                result = {"ok": False, "error": f"Unknown tool: {tname}"}

            _emit_agui(emitter, "TOOL_CALL_END", toolCallId=tc_id)
            _emit_agui(
                emitter,
                "TOOL_CALL_RESULT",
                toolCallId=tc_id,
                content=json.dumps({"ok": result.get("ok"), "exit_code": result.get("exit_code")}, ensure_ascii=False),
            )
            tool_feedback_parts.append(f"Tool result for `{tname}`:\n{json.dumps(result, ensure_ascii=False)}")

        messages.append({"role": "user", "content": "\n\n".join(tool_feedback_parts)})
        if completed_flag:
            break

    # Export verified artifacts to run work_dir (immediately previewable in UI!)
    py_src = sandbox.agent_dir / chosen_py
    if not py_src.is_file():
        # Look for any .py script written by the agent
        py_candidates = sorted(sandbox.agent_dir.glob("*.py"))
        py_src = py_candidates[0] if py_candidates else None

    if py_src and py_src.is_file():
        shutil.copy2(py_src, work_dir / py_export_name)
    else:
        (work_dir / py_export_name).write_text(_build_fallback_analysis_py(excel_path, profile), encoding="utf-8")

    md_src = sandbox.agent_dir / chosen_md
    if not md_src.is_file():
        md_candidates = sorted(sandbox.agent_dir.glob("*.md"))
        md_src = md_candidates[0] if md_candidates else None

    if md_src and md_src.is_file() and md_src.stat().st_size > 40:
        shutil.copy2(md_src, work_dir / md_filename)
    else:
        (work_dir / md_filename).write_text(
            _build_verified_fallback_md(excel_path, profile, terminal_outputs, py_export_name),
            encoding="utf-8",
        )

    emit_file_status(
        "completed",
        "Analysis complete · .md & analysis.py ready",
        md_artifact=md_filename,
        py_artifact=py_export_name,
        profile=profile,
    )

    return {
        "profile": profile,
        "md_artifact": md_filename,
        "py_artifact": py_export_name,
    }


def run_parallel_excel_explorers(
    excel_paths: list[Path],
    work_dir: Path,
    emitter: AguiEmitter | None = None,
    pause_check: Callable[[], None] | None = None,
) -> list[dict[str, Any]]:
    """Launch parallel isolated Excel Explorer Agents (one per uploaded workbook) with live AG-UI status."""
    if pause_check:
        pause_check()

    max_workers = min(4, max(1, len(excel_paths)))
    results_by_name: dict[str, dict[str, Any]] = {}

    # Announce all queued files immediately so UI shows all cards active in parallel
    for p in excel_paths:
        _emit_agui(
            emitter,
            "CUSTOM",
            name="source.file_status",
            value={"filename": p.name, "status": "queued", "message": "Launching isolated explorer agent…"},
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(explore_single_workbook_agent, p, work_dir, emitter, 8, pause_check): p
            for p in excel_paths
        }
        for future in as_completed(futures):
            p = futures[future]
            try:
                res = future.result()
                results_by_name[p.name] = res
            except Exception as exc:
                _emit_agui(
                    emitter,
                    "CUSTOM",
                    name="source.file_status",
                    value={"filename": p.name, "status": "failed", "message": f"Explorer failed: {exc}"},
                )
                raise

    # Preserve original upload order
    return [results_by_name[p.name]["profile"] for p in excel_paths]
