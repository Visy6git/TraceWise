"""Shared pytest fixtures isolating DB, immutable storage, and synthetic PBRER inputs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import docx
import openpyxl
import pytest

from app.services.database import (
    ArtifactRepository,
    ClaimRepository,
    Database,
    EvaluationRepository,
    RunRepository,
)
from app.services.event_stream import EventBroker
from app.services.storage import StorageService


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Redirect SQLite DB, artifact storage, and AG-UI event broker to tmp_path."""
    db = Database(tmp_path / "test-tracewise.sqlite")
    storage = StorageService(tmp_path / "runtime")
    run_repo = RunRepository(db)
    claim_repo = ClaimRepository(db)
    artifact_repo = ArtifactRepository(db)
    eval_repo = EvaluationRepository(db)
    broker = EventBroker()

    # Patch services module singletons
    import app.services.database as db_mod
    import app.services.event_stream as ev_mod
    import app.services.storage as st_mod

    monkeypatch.setattr(db_mod, "default_db", db)
    monkeypatch.setattr(db_mod, "default_run_repo", run_repo)
    monkeypatch.setattr(db_mod, "default_claim_repo", claim_repo)
    monkeypatch.setattr(db_mod, "default_artifact_repo", artifact_repo)
    monkeypatch.setattr(db_mod, "default_eval_repo", eval_repo)
    monkeypatch.setattr(st_mod, "default_storage", storage)
    monkeypatch.setattr(ev_mod, "default_broker", broker)

    # Patch imported bindings in API routers & stage orchestrators
    targets_run = [
        "app.api.runs",
        "app.api.stages",
        "app.api.review",
        "app.api.claims",
        "app.api.sources",
        "app.stages.stage_1_claims.orchestrator",
        "app.stages.stage_2_rules.orchestrator",
    ]
    targets_claim = [
        "app.api.claims",
        "app.stages.stage_1_claims.orchestrator",
        "app.stages.stage_1_claims.claim_tools",
        "app.stages.stage_2_rules.orchestrator",
    ]
    targets_art = [
        "app.api.artifacts",
        "app.stages.stage_1_claims.orchestrator",
        "app.stages.stage_1_claims.source_explorer",
        "app.stages.stage_2_rules.orchestrator",
    ]
    targets_storage = [
        "app.api.runs",
        "app.api.artifacts",
        "app.api.claims",
        "app.api.sources",
        "app.api.sections",
        "app.stages.stage_1_claims.document_understanding",
        "app.stages.stage_1_claims.source_explorer",
        "app.stages.stage_1_claims.orchestrator",
        "app.stages.stage_2_rules.orchestrator",
    ]
    targets_broker = [
        "app.api.stages",
        "app.harness.runner",
        "app.stages.stage_1_claims.orchestrator",
        "app.stages.stage_1_claims.source_explorer",
        "app.stages.stage_1_claims.claim_tools",
        "app.stages.stage_1_claims.claim_extractor",
        "app.stages.stage_2_rules.orchestrator",
        "app.stages.stage_3_evaluation.placeholder",
    ]

    import importlib

    for mod_name in targets_run:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "default_run_repo", run_repo)
    for mod_name in targets_claim:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "default_claim_repo", claim_repo)
    for mod_name in targets_art:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "default_artifact_repo", artifact_repo)
    for mod_name in targets_storage:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "default_storage", storage)
    for mod_name in targets_broker:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "default_broker", broker)

    eval_api = importlib.import_module("app.api.evaluation")
    monkeypatch.setattr(eval_api, "default_eval_repo", eval_repo)

    # Default tests to deterministic offline mode unless explicitly overridden
    import app.config as cfg
    import app.api.runs as runs_api
    import app.stages.stage_1_claims.claim_extractor as ce_mod
    import app.stages.stage_1_claims.source_explorer as se_mod
    import app.stages.stage_2_rules.orchestrator as r_mod

    for mod in (cfg, runs_api, ce_mod, se_mod, r_mod):
        if hasattr(mod, "MOCK_RUNS_ENABLED"):
            monkeypatch.setattr(mod, "MOCK_RUNS_ENABLED", True)

    return {
        "db": db,
        "storage": storage,
        "run_repo": run_repo,
        "claim_repo": claim_repo,
        "artifact_repo": artifact_repo,
        "eval_repo": eval_repo,
        "broker": broker,
        "tmp_path": tmp_path,
    }


def create_synthetic_pbrer_dataset(base_dir: Path) -> tuple[Path, list[Path]]:
    """Build synthetic Section 16.3 PBRER .docx + matching .xlsx/.csv source extracts."""
    base_dir.mkdir(parents=True, exist_ok=True)
    doc_path = base_dir / "Synthetic_PBRER_2025.docx"

    doc = docx.Document()
    doc.add_heading("16 Integrated Benefit-Risk Analysis", level=1)
    doc.add_heading("16.3 Benefit-risk evaluation", level=2)
    doc.add_paragraph("Overall benefit-risk profile for the reporting interval.")

    doc.add_heading("16.3.1 Important identified risks", level=3)
    doc.add_heading("16.3.1.1 Hepatic adverse events", level=4)
    doc.add_paragraph(
        "During the reporting interval, cumulative hepatic monitoring identified interval cases in post-marketing data."
    )
    table = doc.add_table(rows=4, cols=2)
    table.cell(0, 0).text = "Parameter"
    table.cell(0, 1).text = "Result"
    table.cell(1, 0).text = "Search criteria"
    table.cell(1, 1).text = "MedDRA SMQ Drug related hepatic disorders (narrow)"
    table.cell(2, 0).text = "Reporting interval / Cumulative cases"
    table.cell(2, 1).text = "235/500"
    table.cell(3, 0).text = "Case characteristics"
    table.cell(3, 1).text = (
        "Of these, 39 (16.6%) cases were serious and 15 (6.4%) case was fatal. "
        "Spontaneous: 180, Report from other studies: 55."
    )

    doc.add_heading("16.3.1.2 Severe skin reactions", level=4)
    doc.add_paragraph(
        "Search criteria: MedDRA HLT Severe cutaneous adverse reactions. "
        "A total of 12 cases met the SCAR interval definition."
    )
    doc.save(str(doc_path))

    # Build Hepatic_CSMR.xlsx with 3 preamble banner rows so header_row_index == 3
    xlsx_path = base_dir / "01_Hepatic_CSMR.xlsx"
    wb = openpyxl.Workbook()
    cover = wb.active
    cover.title = "Cover"
    cover.append(["Report Export", "Synthetic Hepatic CSMR"])
    cover.append(["Cutoff Date", "2025-12-31"])

    ws = wb.create_sheet("Case Listing")
    ws.append(["CONFIDENTIAL PHARMACOVIGILANCE EXTRACT"])
    ws.append(["Filter: SMQ Hepatic Disorders"])
    ws.append([])
    ws.append(["Case Number", "Seriousness", "Death", "Primary Source", "MedDRA PT"])

    for i in range(1, 236):
        serious = "Yes" if i <= 39 else "No"
        death = "Yes" if i <= 15 else "No"
        src = "Spontaneous" if i <= 180 else "Report from other studies"
        pt = "Hepatotoxicity" if i % 2 == 0 else "ALT increased"
        ws.append([f"CASE-{i:04d}", serious, death, src, pt])
        # Duplicate 10 rows for multiple events on same case to verify dedup on Case Number == 235
        if i <= 10:
            ws.append([f"CASE-{i:04d}", serious, death, src, "AST increased"])

    wb.save(str(xlsx_path))
    wb.close()

    # Build Skin_CSMR.csv with 12 distinct cases
    csv_path = base_dir / "02_Severe_skin_CSMR.csv"
    lines = ["Case Number,Seriousness,MedDRA PT"]
    for i in range(1, 13):
        lines.append(f"SKIN-{i:03d},Yes,Stevens-Johnson syndrome")
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return doc_path, [xlsx_path, csv_path]

