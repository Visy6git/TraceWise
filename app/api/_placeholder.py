"""Shared explicit placeholder response helper."""
from fastapi import HTTPException, status


def not_implemented(operation: str, implementation_notes: str) -> None:
    """Return a clear 501 instead of pretending an agent or persistence operation ran."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "STARTER_BACKEND_NOT_IMPLEMENTED",
            "operation": operation,
            "message": "This repository is a UI-complete starter. Backend execution is intentionally a placeholder.",
            "implementation_notes": implementation_notes,
        },
    )
