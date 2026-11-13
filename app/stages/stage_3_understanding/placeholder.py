"""Compatibility shim for the repository's former Stage 3 evaluation placeholder."""
from app.stages.stage_3_understanding.orchestrator import run_understanding_stage


def run_evaluation_stage(run_id: str, expected_stage_2_manifest_hash: str | None = None):
    """Backward-compatible import while API/UI labels migrate from evaluation to understanding."""
    if not expected_stage_2_manifest_hash:
        raise ValueError("expected_stage_2_manifest_hash is required for Stage 3 Understanding")
    return run_understanding_stage(run_id, expected_stage_2_manifest_hash)
