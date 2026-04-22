from __future__ import annotations

import json
import subprocess
import shutil
import tomllib
from collections import deque
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from app.config import Settings
from app.models.dto import (
    CodexCapabilitiesResponse,
    CodexCommandSpec,
    CodexSessionBridgeRequest,
    CodexSessionBridgeResponse,
    CodexSessionSummary,
    CodexSummaryResponse,
)


def _load_codex_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with config_path.open("rb") as handle:
        return tomllib.load(handle)


def _session_index_path(settings: Settings) -> Path:
    return settings.codex_home / "session_index.jsonl"


@lru_cache(maxsize=1)
def _probe_codex_cli() -> dict[str, object]:
    codex_path = shutil.which("codex")
    if codex_path is None:
        return {
            "available": False,
            "version": None,
            "resume": False,
            "exec_resume": False,
            "app_server": False,
            "exec_server": False,
            "mcp_server": False,
        }

    def command_available(argv: list[str]) -> bool:
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=6, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    try:
        version_result = subprocess.run(
            ["codex", "--version"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        version = version_result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        version = None

    return {
        "available": True,
        "version": version,
        "resume": command_available(["codex", "resume", "--help"]),
        "exec_resume": command_available(["codex", "exec", "resume", "--help"]),
        "app_server": command_available(["codex", "app-server", "--help"]),
        "exec_server": command_available(["codex", "exec-server", "--help"]),
        "mcp_server": command_available(["codex", "mcp-server", "--help"]),
    }


def get_codex_summary(settings: Settings) -> CodexSummaryResponse:
    config_path = settings.codex_home / "config.toml"
    session_index_path = _session_index_path(settings)
    config_data = _load_codex_config(config_path)
    trusted_projects = config_data.get("projects", {})
    probe = _probe_codex_cli()

    return CodexSummaryResponse(
        codex_home=str(settings.codex_home),
        config_path=str(config_path),
        session_index_path=str(session_index_path),
        config_exists=config_path.exists(),
        session_index_exists=session_index_path.exists(),
        codex_cli_available=bool(probe["available"]),
        trusted_project_count=len(trusted_projects),
        integration_mode="cli-bridge-first",
        note=(
            "Prefer Codex CLI and server entry points first. "
            "Session file parsing is available as a UI/indexing fallback."
        ),
    )


def load_recent_sessions(settings: Settings, limit: int = 8) -> list[CodexSessionSummary]:
    session_index_path = _session_index_path(settings)
    if not session_index_path.exists():
        return []

    tail: deque[str] = deque(maxlen=limit)
    with session_index_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                tail.append(line)

    sessions: list[CodexSessionSummary] = []
    for raw_line in reversed(tail):
        payload = json.loads(raw_line)
        sessions.append(
            CodexSessionSummary(
                id=payload.get("id", "unknown"),
                thread_name=payload.get("thread_name", "Untitled session"),
                updated_at=payload.get("updated_at", ""),
            )
        )
    return sessions


def find_session_summary(session_id: str, settings: Settings) -> CodexSessionSummary:
    session_index_path = _session_index_path(settings)
    if not session_index_path.exists():
        raise HTTPException(status_code=404, detail=f"Session index not found: {session_index_path}")

    matched_payload: dict | None = None
    with session_index_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("id") == session_id:
                matched_payload = payload

    if matched_payload is None:
        raise HTTPException(status_code=404, detail=f"Codex session not found: {session_id}")

    return CodexSessionSummary(
        id=matched_payload.get("id", session_id),
        thread_name=matched_payload.get("thread_name", "Untitled session"),
        updated_at=matched_payload.get("updated_at", ""),
    )


def get_codex_capabilities(settings: Settings) -> CodexCapabilitiesResponse:
    config_path = settings.codex_home / "config.toml"
    session_index_path = _session_index_path(settings)
    probe = _probe_codex_cli()

    return CodexCapabilitiesResponse(
        codex_cli_available=bool(probe["available"]),
        version=probe["version"] if isinstance(probe["version"], str | type(None)) else None,
        resume_available=bool(probe["resume"]),
        exec_resume_available=bool(probe["exec_resume"]),
        app_server_available=bool(probe["app_server"]),
        exec_server_available=bool(probe["exec_server"]),
        mcp_server_available=bool(probe["mcp_server"]),
        config_path=str(config_path),
        session_index_path=str(session_index_path),
        note=(
            "Session continuation should prefer CLI or server entry points. "
            "Internal Codex files remain a secondary indexing fallback."
        ),
    )


def _locate_session_log(settings: Settings, session_id: str) -> str | None:
    search_roots = [
        settings.codex_home / "sessions",
        settings.codex_home / "archived_sessions",
    ]
    pattern = f"*{session_id}.jsonl"

    for root in search_roots:
        if not root.exists():
            continue
        for candidate in root.rglob(pattern):
            return str(candidate)
    return None


def build_session_bridge(
    session_id: str,
    request: CodexSessionBridgeRequest,
    settings: Settings,
) -> CodexSessionBridgeResponse:
    session = find_session_summary(session_id, settings)
    capabilities = get_codex_capabilities(settings)
    commands: list[CodexCommandSpec] = []
    warnings: list[str] = []

    if not capabilities.codex_cli_available:
        warnings.append("Codex CLI is not available on PATH, so session continuation commands cannot be built.")

    if capabilities.resume_available:
        argv = ["codex", "resume"]
        if request.project_path:
            argv.extend(["-C", request.project_path])
        if request.sandbox_mode:
            argv.extend(["-s", request.sandbox_mode])
        if request.approval_policy:
            argv.extend(["-a", request.approval_policy])
        argv.append(session_id)
        if request.prompt:
            argv.append(request.prompt)
        commands.append(
            CodexCommandSpec(
                argv=argv,
                cwd=request.project_path,
                mode="interactive",
                purpose="Continue the selected Codex session in interactive mode.",
            )
        )

    if capabilities.exec_resume_available:
        argv = ["codex", "exec"]
        if request.project_path:
            argv.extend(["-C", request.project_path])
        if request.sandbox_mode:
            argv.extend(["-s", request.sandbox_mode])
        argv.extend(["resume", session_id])
        if request.prompt:
            argv.append(request.prompt)
        commands.append(
            CodexCommandSpec(
                argv=argv,
                cwd=request.project_path,
                mode="non_interactive",
                purpose="Continue the selected Codex session in non-interactive mode for orchestration use.",
            )
        )

    if not commands:
        warnings.append("No resumable Codex command path was detected for this environment.")

    warnings.append("Codex continuation is adapter-level behavior and may vary with upstream CLI releases.")

    return CodexSessionBridgeResponse(
        session=session,
        project_path=request.project_path,
        session_log_path=_locate_session_log(settings, session_id),
        can_resume=bool(commands),
        commands=commands,
        strategies=[
            "interactive-resume",
            "non-interactive-resume",
            "session-file-linking",
        ],
        warnings=warnings,
    )


def discover_codex_projects(settings: Settings) -> list[Path]:
    config_path = settings.codex_home / "config.toml"
    config_data = _load_codex_config(config_path)
    project_map = config_data.get("projects", {})
    existing_paths: list[Path] = []

    for raw_path in project_map.keys():
        path = Path(raw_path)
        if path.exists():
            existing_paths.append(path)

    return existing_paths
