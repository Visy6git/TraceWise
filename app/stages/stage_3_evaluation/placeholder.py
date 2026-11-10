"""Stage 3 Independent Evaluation placeholder module."""
from __future__ import annotations

from typing import Any

from app.services.event_stream import default_broker


def run_evaluation_stage(run_id: str) -> dict[str, Any]:
    """Explicit placeholder for Stage 3 (Independent Evaluation & Validation)."""
    msg = (
        "Stage 3 (Independent Evaluation & Validation) is currently left as a placeholder "
        "and is not executed yet."
    )
    default_broker.emit_stage_update(run_id, "evaluation", "placeholder", progress=0)
    default_broker.emit_activity(
        run_id=run_id,
        stage="evaluation",
        title="Stage 3 is a placeholder",
        detail=msg,
        kind="system",
        status="warning",
    )
    return {
        "run_id": run_id,
        "stage": "evaluation",
        "status": "placeholder",
        "is_placeholder": True,
        "accepted": False,
        "message": msg,
    }

