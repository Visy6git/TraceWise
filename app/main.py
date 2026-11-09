"""TraceWise API application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import artifacts, claims, evaluation, events, review, runs, sections, sources, stages
from app.config import BEDROCK_ENABLED, MOCK_RUNS_ENABLED

app = FastAPI(
    title="TraceWise API",
    version="0.1.0",
    description="Reviewer-gated PBRER evidence reconciliation prototype.",
)

# Local development only. Replace with explicit deployment origins before exposure.
# Allow the Vite dev server on either host (localhost / 127.0.0.1) and any port,
# so the browser does not block requests with a "Failed to fetch" CORS error when
# Vite picks a different port or host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    return {
        "status": "ok",
        "service": "tracewise-api",
        "mode": "mock" if MOCK_RUNS_ENABLED else "live",
        "bedrock": "enabled" if BEDROCK_ENABLED else "disabled",
    }
