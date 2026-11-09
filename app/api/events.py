"""AG-UI Events SSE streaming API router."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.services.event_stream import stream_run_events

router = APIRouter(tags=["events"])


@router.get("/runs/{run_id}/events")
def stream_events(run_id: str, cursor: str | None = None) -> StreamingResponse:
    """Stream live AG-UI 1.0 JSON event frames over SSE with replay support."""
    return StreamingResponse(
        stream_run_events(run_id, cursor=cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
