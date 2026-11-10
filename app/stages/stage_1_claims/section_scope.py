"""Scope PBRER reports to Section 16.3 and render FULL context per subsection."""
from __future__ import annotations

import re
from typing import Any

TARGET_SECTION = "16.3"

_STOPWORDS = {
    "information", "important", "identified", "potential", "risks", "risk",
    "other", "categorised", "such", "with", "after", "and", "the", "new",
    "update", "missing", "evaluation", "signal", "signals", "patients",
    "syndrome", "rebound", "worsening", "treatment", "post", "withdrawal",
}


def _num_key(number: str) -> list[int]:
    parts: list[int] = []
    for piece in number.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return parts


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _keywords(title: str) -> list[str]:
    tokens = _normalize(title).split()
    return [t for t in tokens if len(t) >= 4 and t not in _STOPWORDS]


def scope_to_section(
    doc_data: dict[str, Any], target_number: str = TARGET_SECTION
) -> dict[str, Any] | None:
    """Return the 16.3 subtree, its scoped blocks, and full per-subsection work units."""
    sections = doc_data["sections"]
    blocks = doc_data["blocks"]

    by_number = {s["number"]: s for s in sections}
    by_id = {s["section_id"]: s for s in sections}
    target = by_number.get(target_number)
    if not target:
        return None

    target_level = target["level"]
    prefix = target_number + "."
    subtree = [
        s for s in sections
        if s["number"] == target_number or s["number"].startswith(prefix)
    ]
    subtree_ids = {s["section_id"] for s in subtree}

    own_blocks: dict[str, list[dict[str, Any]]] = {sid: [] for sid in subtree_ids}
    scoped_blocks: list[dict[str, Any]] = []
    for b in blocks:
        if b.get("section_id") in subtree_ids:
            scoped_blocks.append(b)
            own_blocks[b["section_id"]].append(b)

    work_units: list[dict[str, Any]] = []
    for s in sorted(subtree, key=lambda x: _num_key(x["number"])):
        content = [b for b in own_blocks.get(s["section_id"], []) if not b.get("is_heading")]
        text_len = sum(len(b.get("text", "")) for b in content if b.get("type") != "table")
        n_tables = sum(1 for b in content if b.get("type") == "table")
        if text_len < 20 and n_tables == 0:
            # Pure container heading with no own prose/tables
            continue

        parent_title = ""
        pid = s.get("parent_id")
        if pid and pid in by_id:
            parent_title = f"{by_id[pid]['number']} {by_id[pid]['title']}"

        work_units.append(
            {
                "section_id": s["section_id"],
                "section_number": s["number"],
                "title": s["title"],
                "parent_title": parent_title,
                "level": s["level"] - target_level,
                "blocks": content,
                "keywords": _keywords(f"{s['title']} {parent_title}"),
            }
        )

    scoped_sections: list[dict[str, Any]] = []
    for s in subtree:
        node = dict(s)
        node["level"] = s["level"] - target_level
        if s["number"] == target_number:
            node["parent_id"] = None
        scoped_sections.append(node)

    return {
        "target": target,
        "subtree_sections": scoped_sections,
        "scoped_blocks": scoped_blocks,
        "work_units": work_units,
    }


def render_subsection_full_context(unit: dict[str, Any]) -> str:
    """Render FULL subsection text + COMPLETE tables (no row truncation) for Strands."""
    lines: list[str] = [
        f"## Subsection {unit['section_number']}: {unit['title']}",
    ]
    if unit.get("parent_title"):
        lines.append(f"Parent section: {unit['parent_title']}")
    lines.append(f"section_id: {unit['section_id']}\n")

    for block in unit.get("blocks", []):
        block_id = block.get("block_id", "")
        if block.get("type") == "table":
            headers = block.get("headers") or []
            rows = block.get("rows") or []
            lines.append(f"### Table [{block_id}]")
            if headers:
                lines.append("| " + " | ".join(str(h).replace("\n", " ") for h in headers) + " |")
                lines.append("| " + " | ".join("---" for _ in headers) + " |")
            for row in rows:
                lines.append("| " + " | ".join(str(c).replace("\n", " ") for c in row) + " |")
            lines.append("")
        else:
            txt = (block.get("text") or "").strip()
            if txt:
                lines.append(f"[{block_id}] {txt}\n")

    return "\n".join(lines).strip()

