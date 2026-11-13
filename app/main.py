"""TraceWise API application."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import artifacts, blueprints, claims, evaluation, events, review, runs, sections, sources, stages
from app.config import (
    BEDROCK_ENABLED,
    BEDROCK_MODEL_ID,
    LMSTUDIO_ENABLED,
    LMSTUDIO_MODEL_ID,
    MOCK_RUNS_ENABLED,
    get_active_llm_provider,
)

app = FastAPI(
    title="TraceWise API",
    version="0.2.0",
    description="Three-stage PBRER evidence extraction, Python rule verification, and Section 16.3 blueprint pipeline.",
)

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
app.include_router(blueprints.router, prefix="/api")
app.include_router(stages.router, prefix="/api")
app.include_router(claims.router, prefix="/api")
app.include_router(artifacts.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(review.router, prefix="/api")


def _runtime_summary() -> dict[str, object]:
    active_provider = get_active_llm_provider()
    active_model = LMSTUDIO_MODEL_ID if active_provider in {"lmstudio", "openai"} else BEDROCK_MODEL_ID
    return {
        "status": "ok",
        "service": "tracewise-api",
        "mode": "mock" if MOCK_RUNS_ENABLED else "live",
        "llm_provider": active_provider,
        "bedrock": "enabled" if BEDROCK_ENABLED else "disabled",
        "lmstudio": "enabled" if (LMSTUDIO_ENABLED or active_provider in {"lmstudio", "openai"}) else "disabled",
        "model_id": active_model,
        "stage_3_placeholder": True,
        "stage_3_understanding": True,
    }


@app.get("/health")
def health() -> dict[str, object]:
    return _runtime_summary()


@app.get("/api/config")
def get_config() -> dict[str, object]:
    return _runtime_summary()
