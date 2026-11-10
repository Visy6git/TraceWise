"""Path resolution, Windows MAX_PATH helpers, and workspace boundary guards."""
from __future__ import annotations

import os
from pathlib import Path


def strip_extended_prefix(path: str | Path) -> Path:
    """Strip Windows \\\\?\\ prefix so cmd.exe and standard tools accept cwd/paths."""
    s = str(path)
    if os.name == "nt":
        if s.startswith("\\\\?\\UNC\\"):
            s = "\\\\" + s[8:]
        elif s.startswith("\\\\?\\") or s.startswith("//?/"):
            s = s[4:]
    return Path(s)


def to_extended_path(path: Path) -> Path:
    """Apply \\\\?\\ prefix on Windows only when exceeding MAX_PATH for file I/O."""
    s = str(strip_extended_prefix(path).resolve())
    if os.name == "nt" and len(s) >= 250 and not s.startswith("\\\\?\\"):
        return Path(f"\\\\?\\{s}")
    return Path(s)


def resolve_path(base: str | Path, path: str | Path) -> Path:
    """Resolve `path` relative to `base` (unless already absolute)."""
    base_clean = strip_extended_prefix(Path(base)).resolve()
    p = strip_extended_prefix(Path(path))
    if p.is_absolute():
        return p.resolve()
    return (base_clean / p).resolve()


def is_within_dir(target: Path, root: Path) -> bool:
    """Return True if `target` resolves inside `root` (case-insensitive on Windows)."""
    target_clean = strip_extended_prefix(target).resolve()
    root_clean = strip_extended_prefix(root).resolve()
    try:
        t_norm = os.path.normcase(str(target_clean))
        r_norm = os.path.normcase(str(root_clean))
        return os.path.commonpath([t_norm, r_norm]) == r_norm
    except ValueError:
        return False


def is_within_any_dir(target: Path, roots: list[Path]) -> bool:
    """Return True if `target` resolves inside any allowed root directory."""
    return any(is_within_dir(target, root) for root in roots)


def display_path_rel_to_cwd(path: str | Path, cwd: Path | None) -> str:
    p = strip_extended_prefix(Path(path))
    if cwd:
        try:
            return str(p.relative_to(strip_extended_prefix(cwd)))
        except ValueError:
            pass
    return str(p)


def ensure_parent_directory(path: str | Path) -> Path:
    p = strip_extended_prefix(Path(path))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def is_binary_file(path: str | Path) -> bool:
    try:
        with open(to_extended_path(Path(path)), "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except OSError:
        return False

