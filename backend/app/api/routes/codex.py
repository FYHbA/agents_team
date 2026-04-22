from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.models.dto import (
    CodexCapabilitiesResponse,
    CodexSessionBridgeRequest,
    CodexSessionBridgeResponse,
    CodexSessionSummary,
    CodexSummaryResponse,
)
from app.services.codex import (
    build_session_bridge,
    get_codex_capabilities,
    get_codex_summary,
    load_recent_sessions,
)

router = APIRouter(prefix="/codex", tags=["codex"])


@router.get("/summary", response_model=CodexSummaryResponse)
def read_codex_summary(settings: Settings = Depends(get_settings)) -> CodexSummaryResponse:
    return get_codex_summary(settings)


@router.get("/capabilities", response_model=CodexCapabilitiesResponse)
def read_codex_capabilities(settings: Settings = Depends(get_settings)) -> CodexCapabilitiesResponse:
    return get_codex_capabilities(settings)


@router.get("/sessions", response_model=list[CodexSessionSummary])
def read_codex_sessions(
    limit: int = Query(default=8, ge=1, le=50),
    settings: Settings = Depends(get_settings),
) -> list[CodexSessionSummary]:
    return load_recent_sessions(settings, limit=limit)


@router.post("/sessions/{session_id}/bridge", response_model=CodexSessionBridgeResponse)
def create_codex_session_bridge(
    session_id: str,
    request: CodexSessionBridgeRequest,
    settings: Settings = Depends(get_settings),
) -> CodexSessionBridgeResponse:
    return build_session_bridge(session_id, request, settings)
