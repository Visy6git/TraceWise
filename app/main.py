"""FastAPI application shell. Agent execution is intentionally not wired in this starter."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import artifacts, claims, events, evaluation, review, runs, sections, sources, stages

app = FastAPI(
    title="TraceWise API",
    version="0.1.0",
    description="Reviewer-gated PBRER evidence reconciliation harness (starter scaffold).",
)

# Local development only. Replace with explicit deployment origins before exposure.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
)

app.include_router(runs.router, prefix="/api")
app.include_router(sections.router, prefix="/api")
app.include_router(sources.router, prefix="/api")
app.include_router(evaluation.router, prefix="/api")
app.include_router(stages.router, prefix="/api")
app.include_router(claims.router, prefix="/api")
app.include_router(artifacts.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(review.router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "tracewise-api", "mode": "starter-placeholder"}
