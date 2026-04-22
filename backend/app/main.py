from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import codex, health, projects, workflows
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    settings.agents_team_home.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        summary="Local-first orchestration backend for multi-agent code workflows.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(codex.router, prefix=settings.api_prefix)
    app.include_router(projects.router, prefix=settings.api_prefix)
    app.include_router(workflows.router, prefix=settings.api_prefix)
    return app


app = create_app()
