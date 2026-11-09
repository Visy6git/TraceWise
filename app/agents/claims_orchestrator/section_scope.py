"""Scope the Stage-1 pipeline to PBRER Section 16.3 and decompose it into work units.

The whole claims pipeline is intentionally restricted to Section 16.3
("Evaluation of Risks and New Information"). This module isolates the 16.3
subtree, groups blocks under their leaf subsections, and turns each content
subsection into a *work unit* that one claim-extraction subagent processes.
Each leaf risk subsection (Cardiac failure, Impulse control, Hallucinations,
DAWS, Augmentation, Dystonia, Suicide-related behaviour, ...) maps naturally
onto the uploaded source workbooks.
"""
from __future__ import annotations

import re
from typing import Any

TARGET_SECTION = "16.3"

# Tokens that carry no discriminating signal for source matching.
_STOPWORDS = {
    "information", "important", "identified", "potential", "risks", "risk",
    "other", "categorised", "such", "with", "after", "and", "the", "new",
    "update", "missing", "evaluation", "signal", "signals", "patients",
    "syndrome", "rebound", "worsening", "treatment", "post", "withdrawal",
}


def _num_key(number: str) -> list[int]:
    parts = []
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
    return [t for t in tokens if len(t) >= 5 and t not in _STOPWORDS]


def scope_to_section(doc_data: dict[str, Any], target_number: str = TARGET_SECTION) -> dict[str, Any] | None:
    """Return the 16.3 subtree, its scoped blocks, and per-subsection work units.

    Returns None when the target section is not present in the document.
    """
    sections = doc_data["sections"]
    blocks = doc_data["blocks"]

    by_number = {s["number"]: s for s in sections}
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
        if text_len < 40 and n_tables == 0:
            # Pure structural container heading (e.g. "16.3.1") with no own prose.
            continue
        work_units.append({
            "section_id": s["section_id"],
            "section_number": s["number"],
            "title": s["title"],
            "level": s["level"] - target_level,
            "blocks": content,
            "keywords": _keywords(s["title"]),
        })

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


def match_sources_for_unit(unit: dict[str, Any], sources: list[dict[str, Any]]) -> list[str]:
    """Pick the source filenames most relevant to a work unit.

    Always includes product-wide ("all") sources; adds risk-specific workbooks
    whose filename overlaps the subsection title keywords. Falls back to every
    source when nothing specific matches.
    """
    keywords = unit.get("keywords") or _keywords(unit.get("title", ""))
    all_sources = [s["original_filename"] for s in sources]

    always: list[str] = []
    specific: list[tuple[int, str]] = []
    for s in sources:
        filename = s["original_filename"]
        norm = _normalize(filename)
        tokens = set(norm.split())
        if "all" in tokens:
            always.append(filename)
            continue
        score = sum(1 for kw in keywords if kw in norm)
        if score:
            specific.append((score, filename))

    specific.sort(key=lambda x: x[0], reverse=True)
    matched = always + [fn for _, fn in specific]
    seen: set[str] = set()
    ordered = [fn for fn in matched if not (fn in seen or seen.add(fn))]

    if not specific:
        # No risk-specific workbook — give the subagent the full source context.
        for fn in all_sources:
            if fn not in seen:
                seen.add(fn)
                ordered.append(fn)
    return ordered
